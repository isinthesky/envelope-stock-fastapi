# -*- coding: utf-8 -*-
"""
Notification Scheduler - 전략 알림 스케줄러

APScheduler 기반 스케줄링:
- 14:57 (월~금): 매수 알림용 OHLCV 캐시 업데이트
- 15:00 (월~금): 골든크로스 스캔 후 "매수 준비/매수 적기" 종목 Telegram 알림
- 09:07 (월~금): 매도 알림용 OHLCV 캐시 업데이트
- 09:10 (월~금): 분석 이력 갱신 후 "매도 권장/강력매도" 종목 Telegram 알림
"""

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from src.adapters.database.connection import get_async_session
from src.adapters.external.telegram import get_telegram_notifier
from src.application.domain.strategy.buy_strategy_service import BuyStrategyService
from src.application.domain.strategy.strategy_service import StrategyService
from src.application.domain.strategy.sell_strategy_service import SellStrategyService
from src.adapters.database.repositories.analysis_history_repository import (
    AnalysisHistoryRepository,
)
from src.application.domain.ohlcv.warmup_service import OHLCVWarmupService


logger = logging.getLogger(__name__)

# 한국 시간대
KST = ZoneInfo("Asia/Seoul")


class NotificationScheduler:
    """
    전략 알림 스케줄러

    APScheduler 기반으로 매수/매도 알림을 스케줄링합니다.
    - 15:00 골든크로스 스캔 → READY_TO_BUY/OPTIMAL_BUY 종목 알림
    - 09:10 매도 분석 갱신 → SELL/STRONG_SELL 종목 알림
    """

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

            # 매수 알림용 데이터 업데이트 (월~금 14:57)
            self.scheduler.add_job(
                self._buy_data_update_job,
                CronTrigger(
                    day_of_week="mon-fri",
                    hour=14,
                    minute=57,
                    timezone=KST,
                ),
                id="buy_data_update",
                name="Buy Data Update (14:57)",
                replace_existing=True,
            )

            # 매수 알림 (월~금 15:00)
            self.scheduler.add_job(
                self._buy_notification_job,
                CronTrigger(
                    day_of_week="mon-fri",
                    hour=15,
                    minute=0,
                    timezone=KST,
                ),
                id="buy_notification",
                name="Buy Signal Notification (15:00)",
                replace_existing=True,
            )

            # 매도 알림용 데이터 업데이트 (월~금 09:07)
            self.scheduler.add_job(
                self._sell_data_update_job,
                CronTrigger(
                    day_of_week="mon-fri",
                    hour=9,
                    minute=7,
                    timezone=KST,
                ),
                id="sell_data_update",
                name="Sell Data Update (09:07)",
                replace_existing=True,
            )

            # 매도 알림 (월~금 09:10)
            self.scheduler.add_job(
                self._sell_notification_job,
                CronTrigger(
                    day_of_week="mon-fri",
                    hour=9,
                    minute=10,
                    timezone=KST,
                ),
                id="sell_notification",
                name="Sell Signal Notification (09:10)",
                replace_existing=True,
            )

            self.scheduler.start()
            self.is_running = True
            logger.info(
                "[NotificationScheduler] Started - "
                "Data Update: 09:07/14:57, Notifications: 09:10/15:00 (Mon-Fri)"
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

        # Telegram 클라이언트 정리
        notifier = get_telegram_notifier()
        await notifier.aclose()

    # ==================== 데이터 업데이트 Job ====================

    async def _buy_data_update_job(self) -> None:
        """
        매수 알림용 데이터 업데이트 Job (14:57)

        유니버스 전체 종목의 OHLCV 캐시를 최신으로 업데이트
        """
        logger.info("[NotificationScheduler] Running buy data update job (14:57)...")

        try:
            async with get_async_session() as session:
                warmup_service = OHLCVWarmupService(session)

                # 오래된 데이터 (3일 이상) 보유 종목만 업데이트
                result = await warmup_service.update_stale_symbols(
                    freshness_days=1,  # 1일 이상 지난 데이터 업데이트
                    concurrency=5,
                )

                logger.info(
                    f"[NotificationScheduler] Buy data update completed: "
                    f"{result.success_count} updated, {result.api_calls_made} API calls, "
                    f"{result.duration_seconds}s"
                )

        except Exception as e:
            logger.error(f"[NotificationScheduler] Buy data update error: {e}")

    async def _sell_data_update_job(self) -> None:
        """
        매도 알림용 데이터 업데이트 Job (09:07)

        매도 추적 중인 종목의 OHLCV 캐시를 최신으로 업데이트
        """
        logger.info("[NotificationScheduler] Running sell data update job (09:07)...")

        try:
            async with get_async_session() as session:
                # 활성 추적 종목 조회
                history_repo = AnalysisHistoryRepository(session)
                active_items = await history_repo.get_active_symbols_with_names("sell")

                if not active_items:
                    logger.info("[NotificationScheduler] No active sell tracking items to update")
                    return

                symbols = [item["symbol"] for item in active_items if item["symbol"]]
                if not symbols:
                    logger.info("[NotificationScheduler] No valid symbols to update")
                    return
                logger.info(f"[NotificationScheduler] Updating {len(symbols)} sell tracking symbols")

                # 해당 종목들만 업데이트
                warmup_service = OHLCVWarmupService(session)
                from src.application.domain.ohlcv.dto import WarmupRequestDTO

                request = WarmupRequestDTO(
                    symbols=symbols,
                    days=300,  # 매도 분석에 필요한 기간
                    interval="1d",
                    force_refresh=True,  # 강제 업데이트
                )

                result = await warmup_service.warmup_symbols(request, concurrency=5)

                logger.info(
                    f"[NotificationScheduler] Sell data update completed: "
                    f"{result.success_count} updated, {result.api_calls_made} API calls, "
                    f"{result.duration_seconds}s"
                )

        except Exception as e:
            logger.error(f"[NotificationScheduler] Sell data update error: {e}")

    # ==================== 매수 알림 Job ====================

    async def _buy_notification_job(self) -> None:
        """
        매수 알림 Job (15:00)

        기존: 골든크로스 스캔 + 재무 필터 후 BUY_INTEREST/READY_TO_BUY/OPTIMAL_BUY 종목 요약 전송

        변경: `/api/v1/strategies/universe/golden-cross-recommendations` 와 동일한 로직으로
             골든크로스 추천 요약(Top 종목 + Top 업종)을 생성해서 Telegram DM으로 전송
        """
        async with self._execution_lock:
            logger.info("[NotificationScheduler] Running buy notification job...")

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
                    recommendations.model_dump(mode="json")
                )

                if sent:
                    logger.info(
                        "[NotificationScheduler] Sent golden cross recommendations summary: "
                        f"candidates={recommendations.buy_candidate_count}, "
                        f"top_stocks={len(recommendations.top_stocks)}, "
                        f"top_industries={len(recommendations.top_industries)}"
                    )
                else:
                    logger.info(
                        "[NotificationScheduler] Telegram disabled or not configured, skipping DM"
                    )

            except Exception as e:
                logger.error(f"[NotificationScheduler] Buy notification error: {e}")

    # ==================== 매도 알림 Job ====================

    async def _sell_notification_job(self) -> None:
        """
        매도 알림 Job (09:10)

        분석 이력에서 활성 추적 종목을 갱신하고,
        SELL/STRONG_SELL 종목을 Telegram으로 알림
        """
        async with self._execution_lock:
            logger.info("[NotificationScheduler] Running sell notification job...")

            try:
                async with get_async_session() as session:
                    # 1. 활성 추적 종목 조회 (종목명 포함)
                    history_repo = AnalysisHistoryRepository(session)
                    active_items = await history_repo.get_active_symbols_with_names("sell")

                    if not active_items:
                        logger.info("[NotificationScheduler] No active sell tracking items")
                        return

                    logger.info(
                        f"[NotificationScheduler] Refreshing {len(active_items)} sell items"
                    )

                    # symbol -> name 매핑
                    symbol_name_map = {
                        item["symbol"]: item["name"] for item in active_items
                    }

                    # 2. 각 종목 매도 분석 갱신
                    sell_service = SellStrategyService(session)
                    sell_alerts: list[dict] = []

                    for item in active_items:
                        symbol = item["symbol"]
                        if not symbol:
                            continue
                        try:
                            result = await sell_service.analyze_sell_signal(symbol)

                            # PHASE_4 (매도 권장) 또는 PHASE_5 (강력 매도)인 경우 알림 대상
                            if result.sell_phase in ["PHASE_4", "PHASE_5"]:
                                # 종목명: 분석 결과에 있으면 사용, 없으면 DB에서 조회한 이름 사용
                                stock_name = result.name or symbol_name_map.get(symbol)
                                sell_alerts.append({
                                    "symbol": result.symbol,
                                    "name": stock_name,
                                    "current_price": float(result.current_price),
                                    "sell_phase": result.sell_phase,
                                    "sell_phase_name": result.sell_phase_name,
                                    "sell_phase_action": result.sell_phase_action,
                                    "sell_reasons": result.sell_reasons,
                                })

                            # Rate limit
                            await asyncio.sleep(0.1)

                        except Exception as e:
                            logger.warning(
                                f"[NotificationScheduler] Failed to analyze {symbol}: {e}"
                            )

                    # 3. 알림 전송
                    notifier = get_telegram_notifier()
                    if sell_alerts:
                        await notifier.send_sell_signals_summary(sell_alerts)
                        logger.info(
                            f"[NotificationScheduler] Sent sell notification for {len(sell_alerts)} stocks"
                        )
                    else:
                        # 결과가 없어도 알림 전송 (시스템 정상 동작 확인용)
                        await notifier.send_no_sell_signals_alert(
                            total_tracked=len(active_items)
                        )
                        logger.info("[NotificationScheduler] No PHASE_4/PHASE_5 stocks found, sent empty alert")

            except Exception as e:
                logger.error(f"[NotificationScheduler] Sell notification error: {e}")

    # ==================== 수동 실행 ====================

    async def execute_buy_notification_now(self) -> dict:
        """매수 알림 수동 실행"""
        await self._buy_notification_job()
        return {"success": True, "message": "Buy notification executed"}

    async def execute_sell_notification_now(self) -> dict:
        """매도 알림 수동 실행"""
        await self._sell_notification_job()
        return {"success": True, "message": "Sell notification executed"}


# ==================== 싱글톤 인스턴스 ====================

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
