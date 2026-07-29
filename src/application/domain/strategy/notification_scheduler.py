# -*- coding: utf-8 -*-
"""
Notification Scheduler - 전략 알림 스케줄러

APScheduler 기반 스케줄링:
- 09:20 (월~금): 09:30 매도 알림용 현재가/분석 데이터 갱신
- 09:30 (월~금): 매도 권장 종목 Telegram 알림
- 11:20 (월~금): 11:30 매수 알림용 현재가/추천 데이터 갱신
- 11:30 (월~금): 골든크로스 추천 종목 Telegram 알림
- 12:20 (월~금): 12:30 매도 알림용 현재가/분석 데이터 갱신
- 12:30 (월~금): 매도 권장 종목 Telegram 알림
- 14:20 (월~금): 14:30 매수 알림용 현재가/추천 데이터 갱신
- 14:30 (월~금): 골든크로스 추천 종목 Telegram 알림
"""

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

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
from src.application.domain.strategy.strategy_service import StrategyService
from src.application.domain.strategy.symbol_validation import (
    filter_tradable_items,
    is_valid_krx_symbol,
)
from src.settings.config import settings


logger = logging.getLogger(__name__)

# 한국 시간대
KST = ZoneInfo("Asia/Seoul")
NOTIFICATION_UPDATE_MAX_AGE = timedelta(minutes=20)
NOTIFICATION_DEDUPE_TTL = timedelta(hours=6)


class NotificationScheduler:
    """
    전략 알림 스케줄러

    APScheduler 기반으로 매수/매도 알림을 스케줄링합니다.
    - 09:30 / 12:30: 매도 분석 갱신 후 SELL/STRONG_SELL 종목 알림
    - 11:30 / 14:30: 골든크로스 추천 종목 알림
    - 각 알림 10분 전 현재가/추천 계산용 데이터 재갱신
    """

    ETF_LEADER_MAP: dict[str, tuple[str, str]] = {
        "396500": ("005930", "000660"),
        "466920": ("329180", "042660"),
        "270810": ("196170", "247540"),
        "0117V0": ("298040", "267260"),
    }

    BUY_SLOTS: tuple[tuple[int, int, int, int, str], ...] = (
        (11, 20, 11, 30, "11:30"),
        (14, 20, 14, 30, "14:30"),
    )
    SELL_SLOTS: tuple[tuple[int, int, int, int, str], ...] = (
        (9, 20, 9, 30, "09:30"),
        (12, 20, 12, 30, "12:30"),
    )

    def __init__(self):
        """초기화"""
        self.is_running = False
        self.scheduler = None
        self._execution_lock = asyncio.Lock()
        self._last_job_results: dict[str, dict] = {}
        self._notification_delivery_cache: dict[str, datetime] = {}

    @classmethod
    def _build_etf_leader_summary(
        cls, symbol: str, analyzed_results: dict[str, dict]
    ) -> str | None:
        """ETF 본체 알림에 붙일 대장주 보조 판정 요약 생성"""
        leader_symbols = cls.ETF_LEADER_MAP.get((symbol or "").strip())
        if not leader_symbols:
            return None

        analyzed_leaders = [analyzed_results.get(leader_symbol) for leader_symbol in leader_symbols]
        analyzed_leaders = [item for item in analyzed_leaders if item]
        if not analyzed_leaders:
            return None

        weak_count = 0
        strong_sell_count = 0
        parts: list[str] = []
        for item in analyzed_leaders:
            final_stage = str(item.get("final_stage") or "")
            name = item.get("name") or item.get("symbol") or "-"
            parts.append(f"{name}:{final_stage or '-'}")
            if final_stage in {"REDUCE_1", "REDUCE_2", "EXIT_ALL"}:
                weak_count += 1
            if final_stage in {"REDUCE_2", "EXIT_ALL"}:
                strong_sell_count += 1

        return (
            f"대장주 확인: {weak_count}/{len(analyzed_leaders)} 약세"
            f" (강매도 {strong_sell_count}) | " + ", ".join(parts)
        )

    @classmethod
    def _filter_duplicate_leader_alerts(cls, pending_sell_alerts: list[dict]) -> list[dict]:
        """ETF 본체가 알림 대상이면 해당 대장주 개별 알림은 숨긴다."""
        etf_alert_symbols = {
            (item.get("symbol") or "").strip()
            for item in pending_sell_alerts
            if (item.get("symbol") or "").strip() in cls.ETF_LEADER_MAP
        }
        hidden_leader_symbols = {
            leader_symbol
            for etf_symbol in etf_alert_symbols
            for leader_symbol in cls.ETF_LEADER_MAP.get(etf_symbol, ())
        }

        return [
            item
            for item in pending_sell_alerts
            if (item.get("symbol") or "").strip() not in hidden_leader_symbols
        ]

    @staticmethod
    def _sanitize_result(value):
        if isinstance(value, dict):
            return {k: NotificationScheduler._sanitize_result(v) for k, v in value.items()}
        if isinstance(value, list):
            return [NotificationScheduler._sanitize_result(v) for v in value[:10]]
        if isinstance(value, tuple):
            return [NotificationScheduler._sanitize_result(v) for v in value[:10]]
        if isinstance(value, datetime):
            return value.isoformat()
        if hasattr(value, "value"):
            return value.value
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

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

    def _record_job_result(
        self,
        job_type: str,
        slot_label: str,
        result: dict | None = None,
        error: str | None = None,
    ) -> None:
        key = f"{job_type}:{slot_label}"
        payload = {
            "job_type": job_type,
            "slot_label": slot_label,
            "recorded_at": datetime.now(KST).isoformat(),
            "success": bool(result and result.get("success", True)) if error is None else False,
        }
        if result:
            payload["result"] = self._sanitize_result(result)
        if error:
            payload["error"] = error
        self._last_job_results[key] = payload

    def _get_notification_freshness(
        self,
        notification_type: str,
        slot_label: str,
        now: datetime | None = None,
    ) -> dict[str, object]:
        """예약 알림이 직전 데이터 업데이트 결과를 사용할 수 있는지 확인한다."""
        if slot_label in {"manual", "-"}:
            return {
                "fresh": True,
                "required": False,
                "status": "manual",
                "message": "manual execution does not require a scheduled update result",
            }

        now = now or datetime.now(KST)
        key = f"{notification_type}_data_update:{slot_label}"
        update_result = self._last_job_results.get(key)
        if not update_result:
            return {
                "fresh": False,
                "required": True,
                "status": "missing",
                "message": f"No {notification_type} data update result for {slot_label}",
            }

        if not update_result.get("success", False):
            return {
                "fresh": False,
                "required": True,
                "status": "failed",
                "message": update_result.get("error") or "Previous data update failed",
            }

        recorded_at_raw = update_result.get("recorded_at")
        try:
            recorded_at = datetime.fromisoformat(str(recorded_at_raw))
        except ValueError:
            return {
                "fresh": False,
                "required": True,
                "status": "invalid_timestamp",
                "message": f"Invalid data update timestamp: {recorded_at_raw}",
            }

        if recorded_at.tzinfo is None:
            recorded_at = recorded_at.replace(tzinfo=KST)
        age_seconds = max((now - recorded_at).total_seconds(), 0.0)
        if age_seconds > NOTIFICATION_UPDATE_MAX_AGE.total_seconds():
            return {
                "fresh": False,
                "required": True,
                "status": "stale",
                "age_seconds": round(age_seconds, 1),
                "message": (
                    f"Data update for {slot_label} is stale " f"({int(age_seconds // 60)}m old)"
                ),
            }

        return {
            "fresh": True,
            "required": True,
            "status": "fresh",
            "age_seconds": round(age_seconds, 1),
            "message": "data update is fresh",
        }

    def _build_notification_signature(self, payload: object) -> str:
        normalized = self._normalize_signature_payload(payload)
        encoded = json.dumps(normalized, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _normalize_signature_payload(value: object):
        if isinstance(value, dict):
            return {
                str(k): NotificationScheduler._normalize_signature_payload(v)
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [NotificationScheduler._normalize_signature_payload(v) for v in value]
        if isinstance(value, tuple):
            return [NotificationScheduler._normalize_signature_payload(v) for v in value]
        if isinstance(value, datetime):
            return value.isoformat()
        if hasattr(value, "value"):
            return value.value
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    def _is_duplicate_notification(
        self,
        notification_type: str,
        slot_label: str,
        signature: str,
        now: datetime | None = None,
    ) -> bool:
        if slot_label in {"manual", "-"}:
            return False
        now = now or datetime.now(KST)
        self._prune_notification_delivery_cache(now)
        key = self._notification_cache_key(notification_type, slot_label, signature, now)
        return key in self._notification_delivery_cache

    def _mark_notification_sent(
        self,
        notification_type: str,
        slot_label: str,
        signature: str,
        now: datetime | None = None,
    ) -> None:
        if slot_label in {"manual", "-"}:
            return
        now = now or datetime.now(KST)
        self._prune_notification_delivery_cache(now)
        key = self._notification_cache_key(notification_type, slot_label, signature, now)
        self._notification_delivery_cache[key] = now

    @staticmethod
    def _notification_cache_key(
        notification_type: str,
        slot_label: str,
        signature: str,
        now: datetime,
    ) -> str:
        return f"{notification_type}:{slot_label}:{now.date().isoformat()}:{signature}"

    def _prune_notification_delivery_cache(self, now: datetime) -> None:
        expired_keys = [
            key
            for key, sent_at in self._notification_delivery_cache.items()
            if now - sent_at > NOTIFICATION_DEDUPE_TTL
        ]
        for key in expired_keys:
            self._notification_delivery_cache.pop(key, None)

    def _build_skipped_notification_result(
        self,
        notification_type: str,
        slot_label: str,
        freshness: dict[str, object],
    ) -> dict[str, object]:
        return {
            "success": False,
            "executed": False,
            "notification_type": notification_type,
            "slot": slot_label,
            "sent": False,
            "skipped": True,
            "skip_reason": freshness.get("message"),
            "freshness": freshness,
        }

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
            "buy_slots": self._slot_definitions(self.BUY_SLOTS, "buy"),
            "sell_slots": self._slot_definitions(self.SELL_SLOTS, "sell"),
            "jobs": jobs,
            "last_job_results": sorted(
                self._last_job_results.values(),
                key=lambda item: item.get("recorded_at", ""),
                reverse=True,
            )[:8],
            "sell_notification_available": True,
        }

    async def start(self) -> None:
        """스케줄러 시작"""
        if self.is_running:
            logger.warning("[NotificationScheduler] Already running")
            return

        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
            from apscheduler.triggers.cron import CronTrigger

            self.scheduler = AsyncIOScheduler(
                timezone=KST,
                job_defaults={
                    # 이벤트 루프 지연으로 초 단위 지각 시에도 잡을 건너뛰지 않도록
                    # 기본 misfire_grace_time(1초)을 5분으로 완화한다.
                    "coalesce": True,
                    "misfire_grace_time": 300,
                },
            )

            # 매수 알림은 BUY_NOTIFICATION_ENABLED로 끌 수 있다.
            # 비활성 시 잡을 등록하지 않아 발송 경로가 열리지 않는다.
            if settings.buy_notification_enabled:
                for update_hour, update_minute, notify_hour, notify_minute, label in self.BUY_SLOTS:
                    self.scheduler.add_job(
                        self._buy_data_update_job,
                        CronTrigger(
                            day_of_week="mon-fri",
                            hour=update_hour,
                            minute=update_minute,
                            timezone=KST,
                        ),
                        kwargs={"slot_label": label},
                        id=f"buy_data_update_{notify_hour:02d}{notify_minute:02d}",
                        name=f"Buy Data Update ({label} alert prep)",
                        replace_existing=True,
                    )
                    self.scheduler.add_job(
                        self._buy_notification_job,
                        CronTrigger(
                            day_of_week="mon-fri",
                            hour=notify_hour,
                            minute=notify_minute,
                            timezone=KST,
                        ),
                        kwargs={"slot_label": label},
                        id=f"buy_notification_{notify_hour:02d}{notify_minute:02d}",
                        name=f"Buy Signal Notification ({label})",
                        replace_existing=True,
                    )
            else:
                logger.info(
                    "[NotificationScheduler] Buy notifications disabled "
                    "(BUY_NOTIFICATION_ENABLED=false) - 11:30/14:30 jobs not registered"
                )

            for update_hour, update_minute, notify_hour, notify_minute, label in self.SELL_SLOTS:
                self.scheduler.add_job(
                    self._sell_data_update_job,
                    CronTrigger(
                        day_of_week="mon-fri",
                        hour=update_hour,
                        minute=update_minute,
                        timezone=KST,
                    ),
                    kwargs={"slot_label": label},
                    id=f"sell_data_update_{notify_hour:02d}{notify_minute:02d}",
                    name=f"Sell Data Update ({label} alert prep)",
                    replace_existing=True,
                )
                self.scheduler.add_job(
                    self._sell_notification_job,
                    CronTrigger(
                        day_of_week="mon-fri",
                        hour=notify_hour,
                        minute=notify_minute,
                        timezone=KST,
                    ),
                    kwargs={"slot_label": label},
                    id=f"sell_notification_{notify_hour:02d}{notify_minute:02d}",
                    name=f"Sell Signal Notification ({label})",
                    replace_existing=True,
                )

            self.scheduler.start()
            self.is_running = True
            logger.info(
                "[NotificationScheduler] Started - "
                "Data Update: 09:20/11:20/12:20/14:20, "
                "Notifications: 09:30/11:30/12:30/14:30 (Mon-Fri)"
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
                    days=300,
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
                freshness = self._get_notification_freshness("buy", slot_label)
                if not freshness["fresh"]:
                    result = self._build_skipped_notification_result("buy", slot_label, freshness)
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
                    stoch_threshold=30.0,
                    gc_only=True,
                    include_etf=True,
                    limit=1000,
                    max_concurrent=None,
                    top_n=5,
                    top_industries_n=3,
                )

                notification_payload = recommendations.model_dump(mode="json")
                signature = self._build_notification_signature(
                    {
                        "top_stocks": notification_payload.get("top_stocks", []),
                        "top_industries": notification_payload.get("top_industries", []),
                        "buy_candidate_count": notification_payload.get("buy_candidate_count"),
                        "errors": notification_payload.get("errors", []),
                    }
                )
                if self._is_duplicate_notification("buy", slot_label, signature):
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
                    self._mark_notification_sent("buy", slot_label, signature)

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
                freshness = self._get_notification_freshness("sell", slot_label)
                if not freshness["fresh"]:
                    result = self._build_skipped_notification_result("sell", slot_label, freshness)
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
                    signature = self._build_notification_signature(
                        {
                            "no_tracked_sell_symbols": True,
                            "status_summary": no_tracking_status,
                        }
                    )
                    if self._is_duplicate_notification("sell", slot_label, signature):
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
                        self._mark_notification_sent("sell", slot_label, signature)
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

                pending_sell_alerts: list[dict] = []
                analyzed_results: dict[str, dict] = {}
                status_summary: list[str] = []

                for item in analyzed_items:
                    stage_value = str(item.sell_stage or "HOLD")
                    # ETF 대장주 맵/요약 조회 키와 일치하도록 strip 정규화 키 사용
                    analyzed_results[(item.symbol or "").strip()] = {
                        "symbol": item.symbol,
                        "name": item.name,
                        "final_stage": stage_value,
                    }

                    stage_name = item.sell_stage_name or stage_value
                    if len(status_summary) < 4:
                        status_summary.append(f"{item.name or item.symbol}: {stage_name}")

                    qualifies = stage_value in {"REDUCE_2", "EXIT_ALL"} or item.sell_phase in {
                        "PHASE_4",
                        "PHASE_5",
                    }
                    if not qualifies:
                        continue

                    entry_price = getattr(item, "entry_price", None)
                    profit_ratio = None
                    try:
                        if entry_price:
                            profit_ratio = (
                                (float(item.current_price) - float(entry_price))
                                / float(entry_price)
                                * 100.0
                            )
                    except (TypeError, ValueError, ZeroDivisionError):
                        profit_ratio = None

                    pending_sell_alerts.append(
                        {
                            "symbol": item.symbol,
                            "name": item.name,
                            "current_price": float(item.current_price),
                            "entry_price": float(entry_price) if entry_price else None,
                            "profit_ratio": profit_ratio,
                            "stoch_k": getattr(item, "stoch_k", None),
                            "rsi": getattr(item, "rsi", None),
                            "ma_gap_ratio": getattr(item, "ma_gap_ratio", None),
                            "sell_ratio_min": getattr(item, "sell_ratio_min", None),
                            "sell_ratio_max": getattr(item, "sell_ratio_max", None),
                            "sell_phase": item.sell_phase,
                            "sell_reasons": item.sell_reasons or [],
                            "final_stage": stage_value,
                            "sell_stage_name": item.sell_stage_name,
                            "volume_ratio": item.volume_ratio,
                            "is_volume_sell_signal": bool(item.is_volume_sell_signal),
                            "is_volume_spike": bool(item.is_volume_spike),
                            "is_volume_peak": False,
                            "is_personal_buying_overheated": bool(
                                getattr(item, "is_personal_buying_overheated", False)
                            ),
                            "market_credit_label": getattr(item, "market_credit_label", None),
                            "is_market_credit_overheated": bool(
                                getattr(item, "is_market_credit_overheated", False)
                            ),
                        }
                    )

                pending_sell_alerts = self._filter_duplicate_leader_alerts(pending_sell_alerts)
                for alert in pending_sell_alerts:
                    leader_summary = self._build_etf_leader_summary(
                        alert["symbol"], analyzed_results
                    )
                    if leader_summary:
                        alert["leader_summary"] = leader_summary

                if pending_sell_alerts:
                    notification_signature_payload: object = {
                        "alerts": pending_sell_alerts,
                        "status_summary": status_summary,
                        "errors": errors[:3],
                    }
                    signature = self._build_notification_signature(notification_signature_payload)
                    if self._is_duplicate_notification("sell", slot_label, signature):
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
                    signature = self._build_notification_signature(notification_signature_payload)
                    if self._is_duplicate_notification("sell", slot_label, signature):
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
                    self._mark_notification_sent("sell", slot_label, signature)

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
