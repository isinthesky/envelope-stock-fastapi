# -*- coding: utf-8 -*-
"""
Notification Scheduler - 전략 알림 스케줄러

APScheduler 기반 스케줄링 (매수만):
- 11:20 (월~금): 11:30 매수 알림용 현재가/추천 데이터 갱신
- 11:30 (월~금): 골든크로스 추천 종목 Telegram 알림
- 14:20 (월~금): 14:30 매수 알림용 현재가/추천 데이터 갱신
- 14:30 (월~금): 골든크로스 추천 종목 Telegram 알림

매도 정보 Telegram msg 스케줄러는 제거됨.
SELL_NOTIFICATION_ENABLED=false 로 제어 (기본 비활성).
"""

import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from src.adapters.cache.redis_client import get_redis_client
from src.adapters.database.connection import get_async_session
from src.adapters.database.models.ohlcv import OHLCVModel
from src.adapters.database.repositories.analysis_history_repository import (
    AnalysisHistoryRepository,
)
from src.adapters.database.repositories.stock_universe_repository import (
    StockUniverseRepository,
)
from src.adapters.external.kofia_client import get_kofia_client
from src.adapters.external.naver.stock_client import get_naver_stock_client
from src.adapters.external.telegram import get_telegram_notifier
from src.application.domain.ohlcv.warmup_service import OHLCVWarmupService
from src.application.domain.strategy import alert_builders
from src.application.domain.strategy.notification_dedupe import NotificationDedupe
from src.application.domain.strategy.scheduler import (
    create_async_scheduler,
    register_cron_job,
)
from src.application.domain.strategy.strategy_service import StrategyService
from src.application.domain.strategy.symbol_validation import (
    filter_tradable_items,
    is_valid_krx_symbol,
)
from src.settings.config import settings

logger = logging.getLogger(__name__)

# 한국 시간대
KST = ZoneInfo("Asia/Seoul")


class NotificationScheduler:
    """
    전략 알림 스케줄러

    APScheduler 기반으로 매수 알림만 스케줄링합니다.
    - 11:30 / 14:30: 골든크로스 추천 종목 Telegram 알림

    매도 정보 Telegram msg 스케줄러(09:30/12:30)는 제거됨.
    (sell_notification_enabled=false)
    """

    # 단일 소스는 settings.etf_leader_map. 하위 호환용 클래스 표면 별칭(동일 dict 참조).
    ETF_LEADER_MAP: dict[str, tuple[str, str]] = settings.etf_leader_map

    def __init__(self):
        """초기화"""
        self.is_running = False
        self.scheduler = None
        self._execution_lock = asyncio.Lock()
        # 신선도/서명/중복 억제 캐시는 NotificationDedupe로 위임한다.
        self._dedupe = NotificationDedupe()

    # ETF 대장주 판정/알림 조립은 alert_builders 모듈로 위임(테스트 표면 유지용 얇은 래퍼).
    @classmethod
    def _build_etf_leader_summary(
        cls, symbol: str, analyzed_results: dict[str, dict]
    ) -> str | None:
        """ETF 본체 알림에 붙일 대장주 보조 판정 요약 생성"""
        return alert_builders.build_etf_leader_summary(symbol, analyzed_results)

    @classmethod
    def _filter_duplicate_leader_alerts(cls, pending_sell_alerts: list[dict]) -> list[dict]:
        """ETF 본체가 알림 대상이면 해당 대장주 개별 알림은 숨긴다."""
        return alert_builders.filter_duplicate_leader_alerts(pending_sell_alerts)

    @staticmethod
    def _slot_definitions(
        slots: tuple[tuple[int, int, int, int, str], ...], kind: str
    ) -> list[dict[str, object]]:
        return [
            {
                "kind": kind,
                "update_time": f"{update_hour:02d}:{update_minute:02d}",
                "notify_time": f"{notify_hour:02d}:{notify_minute:02d}",
                "label": label,
            }
            for update_hour, update_minute, notify_hour, notify_minute, label in slots
        ]

    # 신선도/서명/중복 억제는 NotificationDedupe로 위임한다.
    # (_record_job_result / _build_notification_signature는 테스트가 직접 호출하므로 얇은 래퍼 유지)
    def _record_job_result(
        self,
        job_type: str,
        slot_label: str,
        result: dict | None = None,
        error: str | None = None,
    ) -> None:
        self._dedupe.record_job_result(job_type, slot_label, result=result, error=error)

    def _build_notification_signature(self, payload: object) -> str:
        return self._dedupe.build_notification_signature(payload)

    @staticmethod
    def _warmup_success(result: object) -> bool:
        return int(getattr(result, "failed_count", 0) or 0) == 0

    @staticmethod
    def _warmup_errors(result: object) -> list[str]:
        return list(getattr(result, "errors", None) or [])

    def get_status(self) -> dict[str, object]:
        jobs: list[dict[str, object]] = []
        if self.scheduler:
            for job in sorted(self.scheduler.get_jobs(), key=lambda item: item.id):
                jobs.append(
                    {
                        "id": job.id,
                        "name": job.name,
                        "next_run_time": (
                            job.next_run_time.isoformat() if job.next_run_time else None
                        ),
                        "pending": getattr(job, "pending", False),
                    }
                )

        notifier = get_telegram_notifier()
        return {
            "is_running": self.is_running,
            "timezone": str(KST),
            "telegram_enabled": bool(getattr(notifier, "enabled", False)),
            "execution_lock_locked": self._execution_lock.locked(),
            "buy_notification_enabled": settings.buy_notification_enabled,
            "buy_slots": self._slot_definitions(settings.buy_notification_slots, "buy"),
            "sell_slots": self._slot_definitions(settings.sell_notification_slots, "sell"),
            "jobs": jobs,
            "last_job_results": sorted(
                self._dedupe.job_results.values(),
                key=lambda item: item.get("recorded_at", ""),
                reverse=True,
            )[:8],
            "sell_notification_enabled": getattr(settings, "sell_notification_enabled", False),
            "sell_notification_available": getattr(settings, "sell_notification_enabled", False),
        }

    @staticmethod
    def _register_slot(scheduler, slot, kind: str, update_fn, notify_fn) -> None:
        """슬롯 1개에 대해 데이터 갱신 잡 + 알림 잡 한 쌍을 등록한다.

        기존 add_job 4중 중복(매수 2 슬롯 × update/notify, 매도 동일)을 제거한다.
        trigger/cron/id/name/kwargs는 기존과 동일하게 보존한다.
        """
        update_hour, update_minute, notify_hour, notify_minute, label = slot
        kind_title = kind.capitalize()
        suffix = f"{notify_hour:02d}{notify_minute:02d}"

        register_cron_job(
            scheduler,
            update_fn,
            hour=update_hour,
            minute=update_minute,
            job_id=f"{kind}_data_update_{suffix}",
            name=f"{kind_title} Data Update ({label} alert prep)",
            kwargs={"slot_label": label},
        )
        register_cron_job(
            scheduler,
            notify_fn,
            hour=notify_hour,
            minute=notify_minute,
            job_id=f"{kind}_notification_{suffix}",
            name=f"{kind_title} Signal Notification ({label})",
            kwargs={"slot_label": label},
        )

    async def start(self) -> None:
        """스케줄러 시작"""
        if self.is_running:
            logger.warning("[NotificationScheduler] Already running")
            return

        try:
            self.scheduler = create_async_scheduler()

            # 매수 알림은 BUY_NOTIFICATION_ENABLED로 끌 수 있다.
            # 비활성 시 잡을 등록하지 않아 발송 경로가 열리지 않는다.
            if settings.buy_notification_enabled:
                for slot in settings.buy_notification_slots:
                    self._register_slot(
                        self.scheduler,
                        slot,
                        "buy",
                        self._buy_data_update_job,
                        self._buy_notification_job,
                    )
            else:
                logger.info(
                    "[NotificationScheduler] Buy notifications disabled "
                    "(BUY_NOTIFICATION_ENABLED=false) - 11:30/14:30 jobs not registered"
                )

            if getattr(settings, "sell_notification_enabled", False):
                for slot in settings.sell_notification_slots:
                    self._register_slot(
                        self.scheduler,
                        slot,
                        "sell",
                        self._sell_data_update_job,
                        self._sell_notification_job,
                    )
            else:
                logger.info(
                    "[NotificationScheduler] Sell notifications disabled "
                    "(SELL_NOTIFICATION_ENABLED=false) - 09:30/12:30 jobs not registered"
                )

            self.scheduler.start()
            self.is_running = True
            logger.info(
                "[NotificationScheduler] Started - "
                "Buy only (sell scheduler removed): 11:20/11:30, 14:20/14:30 (Mon-Fri)"
            )

        except ImportError:
            logger.warning("[NotificationScheduler] APScheduler not installed, skipping")
        except Exception as e:
            logger.error(f"[NotificationScheduler] Failed to start: {e}")

    async def stop(self) -> None:
        """스케줄러 중지"""
        if self.scheduler:
            self.scheduler.shutdown(wait=False)
            self.is_running = False
            logger.info("[NotificationScheduler] Stopped")

        notifier = get_telegram_notifier()
        await notifier.aclose()

    # ==================== 데이터 업데이트 Job ====================

    async def _refresh_external_risk_caches(self) -> dict:
        """시장 신용/개인 수급 캐시 선갱신"""
        result: dict = {
            "market_credit": {},
            "personal_flow_refreshed": 0,
            "personal_flow_symbols": [],
        }

        try:
            result["market_credit"] = await get_kofia_client().refresh_market_credit_cache(
                start_date="20260101",
                end_date=datetime.now(KST).strftime("%Y%m%d"),
            )
        except Exception as e:
            logger.warning(f"[NotificationScheduler] Market credit cache refresh failed: {e}")

        try:
            async with get_async_session() as session:
                history_repo = AnalysisHistoryRepository(session)
                active_items = await history_repo.get_active_symbols_with_names("sell")
            naver_client = get_naver_stock_client()
            # 외부(네이버) 조회에는 strip 정규화된 심볼을 전달한다
            symbols = list(
                dict.fromkeys(
                    (item.get("symbol") or "").strip()
                    for item in active_items
                    if is_valid_krx_symbol(item.get("symbol"))
                )
            )

            sem = asyncio.Semaphore(5)

            async def _refresh_one(sym: str) -> bool:
                async with sem:
                    try:
                        await naver_client.refresh_personal_flow_cache(sym)
                        return True
                    except Exception as e:
                        logger.warning(
                            f"[NotificationScheduler] Personal flow cache refresh failed for {sym}: {e}"
                        )
                        return False

            results_list = await asyncio.gather(*[_refresh_one(s) for s in symbols])
            for sym, ok in zip(symbols, results_list):
                if ok:
                    result["personal_flow_refreshed"] += 1
                    result["personal_flow_symbols"].append(sym)
        except Exception as e:
            logger.warning(f"[NotificationScheduler] Personal flow refresh batch failed: {e}")

        return result

    async def _buy_data_update_job(self, slot_label: str = "-") -> dict:
        """
        매수 알림용 데이터 업데이트 Job

        유니버스 전체 종목의 OHLCV 캐시를 최신으로 업데이트합니다.
        """
        logger.info(
            f"[NotificationScheduler] Running buy data update job for {slot_label} alert..."
        )

        try:
            async with get_async_session() as session:
                warmup_service = OHLCVWarmupService(session)

                result = await warmup_service.update_stale_symbols(
                    freshness_days=1,
                    concurrency=5,
                )
                risk_cache_result = await self._refresh_external_risk_caches()
                warmup_success = self._warmup_success(result)
                warmup_errors = self._warmup_errors(result)

                payload = {
                    "success": warmup_success,
                    "slot": slot_label,
                    "updated_count": result.success_count,
                    "failed_count": int(getattr(result, "failed_count", 0) or 0),
                    "errors": warmup_errors[:5],
                    "api_calls_made": result.api_calls_made,
                    "duration_seconds": result.duration_seconds,
                    "risk_cache": risk_cache_result,
                }
                logger.info(
                    f"[NotificationScheduler] Buy data update completed for {slot_label}: "
                    f"{result.success_count} updated, "
                    f"{getattr(result, 'failed_count', 0)} failed, "
                    f"{result.api_calls_made} API calls, "
                    f"{result.duration_seconds}s, risk_cache={risk_cache_result}"
                )
                self._record_job_result(
                    "buy_data_update",
                    slot_label,
                    result=payload,
                    error=(
                        None if warmup_success else "; ".join(warmup_errors[:3]) or "Warmup failed"
                    ),
                )
                return payload

        except Exception as e:
            logger.error(f"[NotificationScheduler] Buy data update error for {slot_label}: {e}")
            payload = {"success": False, "slot": slot_label, "error": str(e)}
            self._record_job_result("buy_data_update", slot_label, result=payload, error=str(e))
            return payload

    async def _sell_data_update_job(self, slot_label: str = "-") -> dict:
        """
        매도 알림용 데이터 업데이트 Job

        매도 추적 중인 종목의 OHLCV 캐시를 최신으로 업데이트합니다.
        """
        logger.info(
            f"[NotificationScheduler] Running sell data update job for {slot_label} alert..."
        )

        try:
            async with get_async_session() as session:
                history_repo = AnalysisHistoryRepository(session)
                active_items = await history_repo.get_active_symbols_with_names("sell")

                active_items, skipped_symbols = filter_tradable_items(active_items)
                if skipped_symbols:
                    logger.info(
                        "[NotificationScheduler] Skipping non-symbol rows (memo etc.) "
                        f"in sell tracking: {', '.join(skipped_symbols)}"
                    )

                if not active_items:
                    logger.info("[NotificationScheduler] No active sell tracking items to update")
                    payload = {
                        "success": True,
                        "slot": slot_label,
                        "updated_count": 0,
                        "tracked_count": 0,
                    }
                    self._record_job_result("sell_data_update", slot_label, result=payload)
                    return payload

                symbols = list(
                    dict.fromkeys(item["symbol"] for item in active_items if item["symbol"])
                )
                if not symbols:
                    logger.info("[NotificationScheduler] No valid symbols to update")
                    payload = {
                        "success": True,
                        "slot": slot_label,
                        "updated_count": 0,
                        "tracked_count": 0,
                    }
                    self._record_job_result("sell_data_update", slot_label, result=payload)
                    return payload
                logger.info(
                    f"[NotificationScheduler] Updating {len(symbols)} sell tracking symbols "
                    f"for {slot_label} alert"
                )

                warmup_service = OHLCVWarmupService(session)
                from src.application.domain.ohlcv.dto import WarmupRequestDTO

                request = WarmupRequestDTO(
                    symbols=symbols,
                    days=max(300, int((settings.gc_long_ma_period + 20) * 1.6)),
                    interval="1d",
                    force_refresh=True,
                )

                result = await warmup_service.warmup_symbols(request, concurrency=5)
                risk_cache_result = await self._refresh_external_risk_caches()
                warmup_success = self._warmup_success(result)
                warmup_errors = self._warmup_errors(result)

                payload = {
                    "success": warmup_success,
                    "slot": slot_label,
                    "tracked_count": len(symbols),
                    "skipped_non_symbol_count": len(skipped_symbols),
                    "updated_count": result.success_count,
                    "failed_count": int(getattr(result, "failed_count", 0) or 0),
                    "errors": warmup_errors[:5],
                    "api_calls_made": result.api_calls_made,
                    "duration_seconds": result.duration_seconds,
                    "risk_cache": risk_cache_result,
                }
                logger.info(
                    f"[NotificationScheduler] Sell data update completed for {slot_label}: "
                    f"{result.success_count} updated, "
                    f"{getattr(result, 'failed_count', 0)} failed, "
                    f"{result.api_calls_made} API calls, "
                    f"{result.duration_seconds}s, risk_cache={risk_cache_result}"
                )
                self._record_job_result(
                    "sell_data_update",
                    slot_label,
                    result=payload,
                    error=(
                        None if warmup_success else "; ".join(warmup_errors[:3]) or "Warmup failed"
                    ),
                )
                return payload

        except Exception as e:
            logger.error(f"[NotificationScheduler] Sell data update error for {slot_label}: {e}")
            payload = {"success": False, "slot": slot_label, "error": str(e)}
            self._record_job_result("sell_data_update", slot_label, result=payload, error=str(e))
            return payload

    # ==================== 매수 알림 Job ====================

    async def _cache_public_recommendation_snapshot(self, recommendations) -> bool:
        """공개 포털(/page/recommendations/)용 추천 스냅샷 캐시 저장

        저장 실패는 warning 로그만 남기고 Telegram 발송/중복 방지/작업 결과 기록을
        중단시키지 않는다.
        """
        try:
            from src.application.domain.strategy.public_dto import (
                PublicRecommendationSnapshotDTO,
            )
            from src.application.domain.strategy.public_strategy_service import (
                PUBLIC_RECOMMENDATION_SNAPSHOT_KEY,
            )

            snapshot = PublicRecommendationSnapshotDTO.from_internal(
                recommendations,
                generated_at=datetime.now(KST),
            )
            redis_client = await get_redis_client()
            saved = await redis_client.set(
                PUBLIC_RECOMMENDATION_SNAPSHOT_KEY,
                snapshot.model_dump(mode="json"),
                ttl=settings.public_strategy_recommendation_ttl_seconds,
            )
            if not saved:
                logger.warning(
                    "[NotificationScheduler] Public recommendation snapshot cache save failed"
                )
            return bool(saved)
        except Exception as e:
            logger.warning(
                f"[NotificationScheduler] Public recommendation snapshot cache error: {e}"
            )
            return False

    def _extract_candle_warning_symbols(self, warnings: list[str]) -> dict[str, str]:
        """캔들 데이터 경고 메시지에서 자동 제외 검토 대상 종목코드 추출."""
        symbols: dict[str, str] = {}

        for warning in warnings:
            symbol = warning.split(":", 1)[0].strip()
            if not symbol:
                continue
            if "No candle data available for" in warning:
                symbols[symbol] = "none"
            elif "Insufficient data for" in warning:
                symbols[symbol] = "insufficient"

        return symbols

    async def _extract_no_candle_symbols(self, warnings: list[str]) -> list[str]:
        """경고 메시지에서 OHLCV가 없거나 오래 끊긴 종목코드 추출"""
        symbol_reasons = self._extract_candle_warning_symbols(warnings)
        if not symbol_reasons:
            return []

        stale_cutoff = datetime.now(KST) - timedelta(days=30)
        valid_symbols: list[str] = []
        async with get_async_session() as session:
            for symbol, reason in symbol_reasons.items():
                stmt = select(
                    func.count(),
                    func.max(OHLCVModel.timestamp),
                ).where(OHLCVModel.symbol == symbol)
                count, latest = (await session.execute(stmt)).one()
                if count == 0:
                    valid_symbols.append(symbol)
                    continue
                if reason == "insufficient" and latest:
                    if latest.tzinfo is None:
                        latest = latest.replace(tzinfo=KST)
                    if latest.astimezone(KST) < stale_cutoff:
                        valid_symbols.append(symbol)

        return valid_symbols

    async def _auto_exclude_symbols_with_missing_candles(self, warnings: list[str]) -> list[str]:
        """반복 경고 대상 중 DB에도 OHLCV가 전혀 없는 종목을 유니버스에서 자동 제외"""
        symbols = await self._extract_no_candle_symbols(warnings)
        if not symbols:
            return []

        excluded_symbols: list[str] = []
        reason = "자동 제외: OHLCV 데이터 없음 (알림 스캔 중 확인)"

        async with get_async_session() as session:
            repo = StockUniverseRepository(session)
            for symbol in symbols:
                stock = await repo.get_by_symbol(symbol, session=session)
                if not stock or stock.is_excluded:
                    continue
                await repo.exclude_stock(symbol, reason, session=session)
                excluded_symbols.append(symbol)
            if excluded_symbols:
                await session.commit()

        if excluded_symbols:
            logger.warning(
                "[NotificationScheduler] Auto-excluded symbols with missing candles: "
                f"{', '.join(excluded_symbols)}"
            )

        return excluded_symbols

    async def _buy_notification_job(self, slot_label: str = "-") -> dict:
        """
        매수 알림 Job

        골든크로스 추천 요약(Top 종목 + Top 업종)을 생성해서 Telegram DM으로 전송합니다.
        실행 시점은 11:30 / 14:30이며, 각 10분 전에 데이터 갱신 Job이 선행됩니다.
        """
        async with self._execution_lock:
            logger.info(f"[NotificationScheduler] Running buy notification job for {slot_label}...")

            try:
                freshness = self._dedupe.get_notification_freshness("buy", slot_label)
                if not freshness["fresh"]:
                    result = self._dedupe.build_skipped_notification_result(
                        "buy", slot_label, freshness
                    )
                    self._record_job_result(
                        "buy_notification",
                        slot_label,
                        result=result,
                        error=str(freshness.get("message")),
                    )
                    return result

                service = StrategyService()

                recommendations = await service.get_golden_cross_recommendations(
                    market=None,
                    stoch_threshold=settings.buy_notification_stoch_threshold,
                    gc_only=True,
                    include_etf=True,
                    limit=settings.buy_notification_scan_limit,
                    max_concurrent=None,
                    top_n=settings.buy_notification_top_n,
                    top_industries_n=settings.buy_notification_top_industries_n,
                )

                # 공개 스냅샷은 계산 직후 캐시한다 — Telegram 비활성/발송 실패/중복 스킵과
                # 무관하게 수동/스케줄 실행으로 계산된 추천은 항상 캐시된다.
                await self._cache_public_recommendation_snapshot(recommendations)

                notification_payload = recommendations.model_dump(mode="json")
                signature = self._dedupe.build_notification_signature(
                    alert_builders.build_buy_signature_payload(notification_payload)
                )
                if self._dedupe.is_duplicate_notification("buy", slot_label, signature):
                    result = {
                        "success": True,
                        "executed": True,
                        "slot": slot_label,
                        "sent": False,
                        "duplicate_skipped": True,
                        "dedupe_signature": signature,
                        "freshness": freshness,
                        "buy_candidate_count": recommendations.buy_candidate_count,
                        "top_stock_count": len(recommendations.top_stocks),
                        "top_industry_count": len(recommendations.top_industries),
                        "warning_count": len(recommendations.errors),
                        "warnings": recommendations.errors[:5],
                    }
                    self._record_job_result("buy_notification", slot_label, result=result)
                    return result

                notifier = get_telegram_notifier()
                sent = await notifier.send_golden_cross_recommendations_summary(
                    notification_payload,
                    slot_label=slot_label,
                )
                if sent:
                    self._dedupe.mark_notification_sent("buy", slot_label, signature)

                auto_excluded_symbols = await self._auto_exclude_symbols_with_missing_candles(
                    recommendations.errors
                )

                result = {
                    "success": bool(sent),
                    "executed": True,
                    "slot": slot_label,
                    "sent": bool(sent),
                    "dedupe_signature": signature,
                    "freshness": freshness,
                    "buy_candidate_count": recommendations.buy_candidate_count,
                    "top_stock_count": len(recommendations.top_stocks),
                    "top_industry_count": len(recommendations.top_industries),
                    "warning_count": len(recommendations.errors),
                    "warnings": recommendations.errors[:5],
                    "auto_excluded_count": len(auto_excluded_symbols),
                    "auto_excluded_symbols": auto_excluded_symbols,
                }

                if sent:
                    logger.info(
                        "[NotificationScheduler] Sent golden cross recommendations summary "
                        f"for {slot_label}: candidates={recommendations.buy_candidate_count}, "
                        f"top_stocks={len(recommendations.top_stocks)}, "
                        f"top_industries={len(recommendations.top_industries)}, "
                        f"warnings={len(recommendations.errors)}"
                    )
                else:
                    logger.info(
                        "[NotificationScheduler] Telegram disabled or not configured, skipping DM"
                    )

                self._record_job_result(
                    "buy_notification",
                    slot_label,
                    result=result,
                    error=None if sent else "Telegram delivery skipped or failed",
                )
                return result

            except Exception as e:
                logger.error(
                    f"[NotificationScheduler] Buy notification error for {slot_label}: {e}"
                )
                result = {
                    "success": False,
                    "slot": slot_label,
                    "sent": False,
                    "error": str(e),
                }
                self._record_job_result("buy_notification", slot_label, result=result, error=str(e))
                return result

    # ==================== 매도 알림 Job ====================

    async def _sell_notification_job(self, slot_label: str = "-") -> dict:
        """
        매도 알림 Job

        분석 이력의 활성 추적 종목을 최신 상태로 재분석하고,
        강한 매도 단계(REDUCE_2/EXIT_ALL) 또는 상위 매도 Phase 종목을 Telegram으로 알립니다.
        실행 시점은 09:30 / 12:30이며, 각 10분 전에 데이터 갱신 Job이 선행됩니다.
        """
        async with self._execution_lock:
            logger.info(
                f"[NotificationScheduler] Running sell notification job for {slot_label}..."
            )

            try:
                freshness = self._dedupe.get_notification_freshness("sell", slot_label)
                if not freshness["fresh"]:
                    result = self._dedupe.build_skipped_notification_result(
                        "sell", slot_label, freshness
                    )
                    self._record_job_result(
                        "sell_notification",
                        slot_label,
                        result=result,
                        error=str(freshness.get("message")),
                    )
                    return result

                async with get_async_session() as session:
                    history_repo = AnalysisHistoryRepository(session)
                    active_items = await history_repo.get_active_symbols_with_names("sell")

                tracked_symbols = list(
                    dict.fromkeys(
                        item.get("symbol")
                        for item in active_items
                        if is_valid_krx_symbol(item.get("symbol"))
                    )
                )
                notifier = get_telegram_notifier()
                if not tracked_symbols:
                    no_tracking_status = ["활성 매도 추적 종목이 없습니다."]
                    signature = self._dedupe.build_notification_signature(
                        {
                            "no_tracked_sell_symbols": True,
                            "status_summary": no_tracking_status,
                        }
                    )
                    if self._dedupe.is_duplicate_notification("sell", slot_label, signature):
                        result = {
                            "success": True,
                            "executed": True,
                            "slot": slot_label,
                            "sent": False,
                            "duplicate_skipped": True,
                            "dedupe_signature": signature,
                            "freshness": freshness,
                            "tracked_count": 0,
                            "analyzed_count": 0,
                            "alert_count": 0,
                            "failed_count": 0,
                            "status_summary": no_tracking_status,
                            "message": "No active sell tracking symbols",
                        }
                        self._record_job_result("sell_notification", slot_label, result=result)
                        return result

                    sent = await notifier.send_no_sell_signals_alert(
                        total_tracked=0,
                        slot_label=slot_label,
                        failed_count=0,
                        failed_summary=None,
                        status_summary=no_tracking_status,
                    )
                    if sent:
                        self._dedupe.mark_notification_sent("sell", slot_label, signature)
                    result = {
                        "success": bool(sent),
                        "executed": True,
                        "slot": slot_label,
                        "sent": bool(sent),
                        "dedupe_signature": signature,
                        "freshness": freshness,
                        "tracked_count": 0,
                        "analyzed_count": 0,
                        "alert_count": 0,
                        "failed_count": 0,
                        "status_summary": no_tracking_status,
                        "message": "No active sell tracking symbols",
                    }
                    self._record_job_result(
                        "sell_notification",
                        slot_label,
                        result=result,
                        error=None if sent else "Telegram delivery skipped or failed",
                    )
                    return result

                refresh_result = await StrategyService().refresh_analysis_history("sell")
                analyzed_items = refresh_result.items
                errors = refresh_result.errors

                pending_sell_alerts, status_summary = alert_builders.assemble_sell_alerts(
                    analyzed_items
                )

                if pending_sell_alerts:
                    notification_signature_payload: object = {
                        "alerts": pending_sell_alerts,
                        "status_summary": status_summary,
                        "errors": errors[:3],
                    }
                    signature = self._dedupe.build_notification_signature(
                        notification_signature_payload
                    )
                    if self._dedupe.is_duplicate_notification("sell", slot_label, signature):
                        result = {
                            "success": True,
                            "executed": True,
                            "slot": slot_label,
                            "sent": False,
                            "duplicate_skipped": True,
                            "dedupe_signature": signature,
                            "freshness": freshness,
                            "tracked_count": len(tracked_symbols),
                            "analyzed_count": len(analyzed_items),
                            "alert_count": len(pending_sell_alerts),
                            "failed_count": len(errors),
                            "failed_summary": errors[:3],
                            "top_alert_symbols": [
                                item["symbol"] for item in pending_sell_alerts[:5]
                            ],
                            "status_summary": status_summary,
                        }
                        self._record_job_result("sell_notification", slot_label, result=result)
                        return result

                    sent = await notifier.send_sell_signals_summary(
                        pending_sell_alerts,
                        slot_label=slot_label,
                        status_summary=status_summary,
                    )
                else:
                    notification_signature_payload = {
                        "no_sell_signals": True,
                        "tracked_count": len(tracked_symbols),
                        "failed_count": len(errors),
                        "failed_summary": errors[:3],
                        "status_summary": status_summary,
                    }
                    signature = self._dedupe.build_notification_signature(
                        notification_signature_payload
                    )
                    if self._dedupe.is_duplicate_notification("sell", slot_label, signature):
                        result = {
                            "success": True,
                            "executed": True,
                            "slot": slot_label,
                            "sent": False,
                            "duplicate_skipped": True,
                            "dedupe_signature": signature,
                            "freshness": freshness,
                            "tracked_count": len(tracked_symbols),
                            "analyzed_count": len(analyzed_items),
                            "alert_count": 0,
                            "failed_count": len(errors),
                            "failed_summary": errors[:3],
                            "top_alert_symbols": [],
                            "status_summary": status_summary,
                        }
                        self._record_job_result("sell_notification", slot_label, result=result)
                        return result

                    sent = await notifier.send_no_sell_signals_alert(
                        total_tracked=len(tracked_symbols),
                        slot_label=slot_label,
                        failed_count=len(errors),
                        failed_summary=errors[:3],
                        status_summary=status_summary,
                    )
                if sent:
                    self._dedupe.mark_notification_sent("sell", slot_label, signature)

                result = {
                    "success": bool(sent),
                    "executed": True,
                    "slot": slot_label,
                    "sent": bool(sent),
                    "dedupe_signature": signature,
                    "freshness": freshness,
                    "tracked_count": len(tracked_symbols),
                    "analyzed_count": len(analyzed_items),
                    "alert_count": len(pending_sell_alerts),
                    "failed_count": len(errors),
                    "failed_summary": errors[:3],
                    "top_alert_symbols": [item["symbol"] for item in pending_sell_alerts[:5]],
                    "status_summary": status_summary,
                }
                self._record_job_result(
                    "sell_notification",
                    slot_label,
                    result=result,
                    error=None if sent else "Telegram delivery skipped or failed",
                )
                return result

            except Exception as e:
                logger.error(
                    f"[NotificationScheduler] Sell notification error for {slot_label}: {e}"
                )
                result = {
                    "success": False,
                    "slot": slot_label,
                    "sent": False,
                    "error": str(e),
                }
                self._record_job_result(
                    "sell_notification", slot_label, result=result, error=str(e)
                )
                return result

    async def execute_buy_notification_now(self, slot_label: str = "manual") -> dict:
        """매수 알림 수동 실행"""
        return await self._buy_notification_job(slot_label=slot_label)

    async def execute_sell_notification_now(self, slot_label: str = "manual") -> dict:
        """매도 알림 수동 실행"""
        return await self._sell_notification_job(slot_label=slot_label)


_notification_scheduler: NotificationScheduler | None = None


def get_notification_scheduler() -> NotificationScheduler:
    global _notification_scheduler
    if _notification_scheduler is None:
        _notification_scheduler = NotificationScheduler()
    return _notification_scheduler
