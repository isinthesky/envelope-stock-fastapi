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
import logging
from datetime import datetime
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
from src.adapters.database.repositories.strategy_repository import StrategyRepository
from src.adapters.database.repositories.strategy_symbol_state_repository import (
    StrategySymbolStateRepository,
)
from src.adapters.external.kofia_client import get_kofia_client
from src.adapters.external.naver.stock_client import get_naver_stock_client
from src.adapters.external.telegram import get_telegram_notifier
from src.application.domain.ohlcv.warmup_service import OHLCVWarmupService
from src.application.domain.strategy.sell_strategy_service import SellStrategyService
from src.application.domain.strategy.strategy_service import StrategyService


logger = logging.getLogger(__name__)

# 한국 시간대
KST = ZoneInfo("Asia/Seoul")


class NotificationScheduler:
    """
    전략 알림 스케줄러

    APScheduler 기반으로 매수/매도 알림을 스케줄링합니다.
    - 09:30 / 12:30: 매도 분석 갱신 후 SELL/STRONG_SELL 종목 알림
    - 11:30 / 14:30: 골든크로스 추천 종목 알림
    - 각 알림 10분 전 현재가/추천 계산용 데이터 재갱신
    """

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

    async def start(self) -> None:
        """스케줄러 시작"""
        if self.is_running:
            logger.warning("[NotificationScheduler] Already running")
            return

        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
            from apscheduler.triggers.cron import CronTrigger

            self.scheduler = AsyncIOScheduler(timezone=KST)

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
            for item in active_items:
                symbol = item.get("symbol")
                if not symbol:
                    continue
                try:
                    await naver_client.refresh_personal_flow_cache(symbol)
                    result["personal_flow_refreshed"] += 1
                    result["personal_flow_symbols"].append(symbol)
                except Exception as e:
                    logger.warning(
                        f"[NotificationScheduler] Personal flow cache refresh failed for {symbol}: {e}"
                    )
        except Exception as e:
            logger.warning(f"[NotificationScheduler] Personal flow refresh batch failed: {e}")

        return result

    async def _buy_data_update_job(self, slot_label: str = "-") -> None:
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

                logger.info(
                    f"[NotificationScheduler] Buy data update completed for {slot_label}: "
                    f"{result.success_count} updated, {result.api_calls_made} API calls, "
                    f"{result.duration_seconds}s, risk_cache={risk_cache_result}"
                )

        except Exception as e:
            logger.error(
                f"[NotificationScheduler] Buy data update error for {slot_label}: {e}"
            )

    async def _sell_data_update_job(self, slot_label: str = "-") -> None:
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

                if not active_items:
                    logger.info(
                        "[NotificationScheduler] No active sell tracking items to update"
                    )
                    return

                symbols = [item["symbol"] for item in active_items if item["symbol"]]
                if not symbols:
                    logger.info("[NotificationScheduler] No valid symbols to update")
                    return
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

                logger.info(
                    f"[NotificationScheduler] Sell data update completed for {slot_label}: "
                    f"{result.success_count} updated, {result.api_calls_made} API calls, "
                    f"{result.duration_seconds}s, risk_cache={risk_cache_result}"
                )

        except Exception as e:
            logger.error(
                f"[NotificationScheduler] Sell data update error for {slot_label}: {e}"
            )

    # ==================== 매수 알림 Job ====================

    async def _extract_no_candle_symbols(self, warnings: list[str]) -> list[str]:
        """경고 메시지에서 OHLCV가 전혀 없는 종목코드 추출"""
        symbols: list[str] = []
        marker = "No candle data available for"

        for warning in warnings:
            if marker not in warning:
                continue
            symbol = warning.split(":", 1)[0].strip()
            if symbol and symbol not in symbols:
                symbols.append(symbol)

        if not symbols:
            return []

        async with get_async_session() as session:
            valid_symbols: list[str] = []
            for symbol in symbols:
                stmt = select(func.count()).select_from(OHLCVModel).where(OHLCVModel.symbol == symbol)
                count = (await session.execute(stmt)).scalar_one()
                if count == 0:
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
            logger.info(
                f"[NotificationScheduler] Running buy notification job for {slot_label}..."
            )

            try:
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

                notifier = get_telegram_notifier()
                sent = await notifier.send_golden_cross_recommendations_summary(
                    recommendations.model_dump(mode="json"),
                    slot_label=slot_label,
                )

                auto_excluded_symbols = await self._auto_exclude_symbols_with_missing_candles(
                    recommendations.errors
                )

                result = {
                    "success": True,
                    "slot": slot_label,
                    "sent": sent,
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

                return result

            except Exception as e:
                logger.error(
                    f"[NotificationScheduler] Buy notification error for {slot_label}: {e}"
                )
                return {
                    "success": False,
                    "slot": slot_label,
                    "sent": False,
                    "error": str(e),
                }

    # ==================== 매도 알림 Job ====================

    async def _sell_notification_job(self, slot_label: str = "-") -> dict:
        """
        매도 알림 Job

        분석 이력에서 활성 추적 종목을 갱신하고,
        SELL/STRONG_SELL 종목을 Telegram으로 알립니다.
        실행 시점은 09:30 / 12:30이며, 각 10분 전에 데이터 갱신 Job이 선행됩니다.
        """
        async with self._execution_lock:
            logger.info(
                f"[NotificationScheduler] Running sell notification job for {slot_label}..."
            )

            try:
                async with get_async_session() as session:
                    history_repo = AnalysisHistoryRepository(session)
                    active_items = await history_repo.get_active_symbols_with_names("sell")

                    if not active_items:
                        logger.info("[NotificationScheduler] No active sell tracking items")
                        return {
                            "success": True,
                            "slot": slot_label,
                            "sent": False,
                            "tracked_count": 0,
                            "sell_alert_count": 0,
                            "warnings": [],
                        }

                    logger.info(
                        f"[NotificationScheduler] Refreshing {len(active_items)} sell items "
                        f"for {slot_label}"
                    )

                    symbol_name_map = {
                        item["symbol"]: item["name"] for item in active_items
                    }

                    sell_service = SellStrategyService(session)
                    sell_alerts: list[dict] = []
                    warnings: list[str] = []

                    # 활성 전략의 보유 종목 진입가/최고가 조회 (페이지 API와 동일한 파라미터 적용)
                    symbol_state_map: dict[str, dict] = {}
                    try:
                        strategy_repo = StrategyRepository(session)
                        state_repo = StrategySymbolStateRepository(session)
                        active_strategies = await strategy_repo.get_active_strategies(session=session)
                        for strategy in active_strategies:
                            for item in active_items:
                                sym = item["symbol"]
                                if sym and sym not in symbol_state_map:
                                    state = await state_repo.get_by_strategy_and_symbol(
                                        strategy.id, sym, session=session
                                    )
                                    if state and state.entry_price:
                                        symbol_state_map[sym] = {
                                            "entry_price": float(state.entry_price),
                                            "highest_price": float(state.highest_price) if state.highest_price else None,
                                            "trailing_stop_activated": state.trailing_stop_activated or False,
                                        }
                    except Exception as e:
                        logger.warning(f"[NotificationScheduler] Failed to load symbol states: {e}")

                    for item in active_items:
                        symbol = item["symbol"]
                        if not symbol:
                            continue
                        try:
                            # 보유 종목 상태에서 진입가/최고가 조회 (페이지 API와 동일)
                            state_info = symbol_state_map.get(symbol, {})

                            result = await sell_service.analyze_sell_signal(
                                symbol,
                                name=item.get("name"),
                                market=item.get("market"),
                                entry_price=state_info.get("entry_price"),
                                highest_price=state_info.get("highest_price"),
                                trailing_stop_activated=state_info.get("trailing_stop_activated", False),
                            )

                            if result.sell_phase in ["PHASE_4", "PHASE_5"]:
                                stock_name = result.name or symbol_name_map.get(symbol)
                                sell_alerts.append(
                                    {
                                        "symbol": result.symbol,
                                        "name": stock_name,
                                        "current_price": float(result.current_price),
                                        "sell_phase": result.sell_phase,
                                        "sell_phase_name": result.sell_phase_name,
                                        "sell_phase_action": result.sell_phase_action,
                                        "sell_stage": result.sell_stage,
                                        "sell_stage_name": result.sell_stage_name,
                                        "final_stage": result.final_stage,
                                        "is_personal_buying_overheated": result.is_personal_buying_overheated,
                                        "is_market_credit_overheated": result.is_market_credit_overheated,
                                        "market_credit_label": result.market_credit_label,
                                        "sell_reasons": result.sell_reasons,
                                    }
                                )

                            await asyncio.sleep(0.1)

                        except Exception as e:
                            warning = f"{symbol}: {e}"
                            warnings.append(warning)
                            logger.warning(
                                f"[NotificationScheduler] Failed to analyze {symbol}: {e}"
                            )

                    notifier = get_telegram_notifier()
                    if sell_alerts:
                        sent = await notifier.send_sell_signals_summary(
                            sell_alerts,
                            slot_label=slot_label,
                        )
                        logger.info(
                            "[NotificationScheduler] Sent sell notification "
                            f"for {len(sell_alerts)} stocks at {slot_label}"
                        )
                    else:
                        sent = await notifier.send_no_sell_signals_alert(
                            total_tracked=len(active_items),
                            slot_label=slot_label,
                        )
                        logger.info(
                            "[NotificationScheduler] No PHASE_4/PHASE_5 stocks found, "
                            f"sent empty alert for {slot_label}"
                        )

                    return {
                        "success": True,
                        "slot": slot_label,
                        "sent": sent,
                        "tracked_count": len(active_items),
                        "sell_alert_count": len(sell_alerts),
                        "warning_count": len(warnings),
                        "warnings": warnings[:5],
                    }

            except Exception as e:
                logger.error(
                    f"[NotificationScheduler] Sell notification error for {slot_label}: {e}"
                )
                return {
                    "success": False,
                    "slot": slot_label,
                    "sent": False,
                    "error": str(e),
                }

    # ==================== 수동 실행 ====================

    async def execute_buy_notification_now(self) -> dict:
        """매수 알림 수동 실행"""
        return await self._buy_notification_job(slot_label="manual")

    async def execute_sell_notification_now(self) -> dict:
        """매도 알림 수동 실행"""
        return await self._sell_notification_job(slot_label="manual")


_notification_scheduler_instance: NotificationScheduler | None = None


def get_notification_scheduler() -> NotificationScheduler:
    """
    NotificationScheduler 싱글톤 인스턴스 반환

    Returns:
        NotificationScheduler: 알림 스케줄러 인스턴스
    """
    global _notification_scheduler_instance
    if _notification_scheduler_instance is None:
        _notification_scheduler_instance = NotificationScheduler()
    return _notification_scheduler_instance
