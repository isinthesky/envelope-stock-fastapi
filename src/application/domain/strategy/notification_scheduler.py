# -*- coding: utf-8 -*-
"""
Notification Scheduler - 전략 알림 스케줄러

APScheduler 기반 스케줄링:
- 15:00 (월~금): 골든크로스 스캔 후 "매수 준비/매수 적기" 종목 Telegram 알림
- 09:10 (월~금): 분석 이력 갱신 후 "매도 권장/강력매도" 종목 Telegram 알림
"""

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from src.adapters.database.connection import get_async_session
from src.adapters.external.telegram import get_telegram_notifier
from src.application.domain.strategy.buy_strategy_service import BuyStrategyService
from src.application.domain.strategy.sell_strategy_service import SellStrategyService
from src.adapters.database.repositories.analysis_history_repository import (
    AnalysisHistoryRepository,
)


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
            logger.info("[NotificationScheduler] Started - Buy: 15:00, Sell: 09:10 (Mon-Fri)")

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

    # ==================== 매수 알림 Job ====================

    async def _buy_notification_job(self) -> None:
        """
        매수 알림 Job (15:00)

        골든크로스 스캔 후 READY_TO_BUY/OPTIMAL_BUY 상태 종목을 Telegram으로 알림
        """
        async with self._execution_lock:
            logger.info("[NotificationScheduler] Running buy notification job...")

            try:
                async for session in get_async_session():
                    buy_service = BuyStrategyService(session)

                    # 골든크로스 스캔 (READY_TO_BUY/OPTIMAL_BUY 필터링)
                    scan_result = await buy_service.scan_golden_cross_candidates(
                        market=None,
                        stoch_threshold=30.0,
                        gc_only=True,
                    )

                    # READY_TO_BUY/OPTIMAL_BUY 종목 필터
                    target_states = {"READY_TO_BUY", "OPTIMAL_BUY"}
                    buy_targets = [
                        {
                            "symbol": s.symbol,
                            "name": s.name,
                            "current_price": float(s.current_price),
                            "ma_short": float(s.ma_short),
                            "ma_long": float(s.ma_long),
                            "stoch_k": s.stoch_k,
                            "gc_state": s.gc_state,
                        }
                        for s in scan_result.stocks
                        if s.gc_state in target_states
                    ]

                    state_order = {"OPTIMAL_BUY": 0, "READY_TO_BUY": 1}
                    buy_targets.sort(key=lambda s: state_order.get(s.get("gc_state"), 99))

                    if buy_targets:
                        notifier = get_telegram_notifier()
                        await notifier.send_buy_signals_summary(buy_targets)
                        logger.info(
                            f"[NotificationScheduler] Sent buy notification for {len(buy_targets)} stocks"
                        )
                    else:
                        logger.info("[NotificationScheduler] No READY_TO_BUY/OPTIMAL_BUY stocks found")

                    break  # 세션 한 번만 사용

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
                async for session in get_async_session():
                    # 1. 활성 추적 종목 조회 (종목명 포함)
                    history_repo = AnalysisHistoryRepository(session)
                    active_items = await history_repo.get_active_symbols_with_names("sell")

                    if not active_items:
                        logger.info("[NotificationScheduler] No active sell tracking items")
                        break

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
                        try:
                            result = await sell_service.analyze_sell_signal(symbol)

                            # SELL 또는 STRONG_SELL인 경우 알림 대상
                            if result.sell_recommendation in ["SELL", "STRONG_SELL"]:
                                # 종목명: 분석 결과에 있으면 사용, 없으면 DB에서 조회한 이름 사용
                                stock_name = result.name or symbol_name_map.get(symbol)
                                sell_alerts.append({
                                    "symbol": result.symbol,
                                    "name": stock_name,
                                    "current_price": float(result.current_price),
                                    "sell_recommendation": result.sell_recommendation,
                                    "sell_signal_strength": result.sell_signal_strength,
                                    "sell_reasons": result.sell_reasons,
                                })

                            # Rate limit
                            await asyncio.sleep(0.1)

                        except Exception as e:
                            logger.warning(
                                f"[NotificationScheduler] Failed to analyze {symbol}: {e}"
                            )

                    # 3. 알림 전송
                    if sell_alerts:
                        notifier = get_telegram_notifier()
                        await notifier.send_sell_signals_summary(sell_alerts)
                        logger.info(
                            f"[NotificationScheduler] Sent sell notification for {len(sell_alerts)} stocks"
                        )
                    else:
                        logger.info("[NotificationScheduler] No SELL/STRONG_SELL stocks found")

                    break  # 세션 한 번만 사용

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
