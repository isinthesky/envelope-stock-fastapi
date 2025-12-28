# -*- coding: utf-8 -*-
"""
Strategy Scheduler - 전략 스케줄러

APScheduler 기반 스케줄링:
- 장 마감 후 전략 실행: 15:35 (월~금, 거래일 캘린더 반영, KST 기준)
- 유니버스 갱신: 토요일 10:00
"""

import asyncio
import logging
from datetime import datetime
from typing import Callable
from zoneinfo import ZoneInfo

from src.adapters.database.connection import get_async_session
from src.adapters.database.models.strategy import StrategyStatus
from src.adapters.database.repositories.strategy_repository import StrategyRepository
from src.adapters.external.kis_api.client import KISAPIClient
from src.application.domain.market_data.service import MarketDataService
from src.application.domain.strategy.golden_cross_engine import GoldenCrossEngine

logger = logging.getLogger(__name__)

# 한국 시간대
KST = ZoneInfo("Asia/Seoul")


class StrategyScheduler:
    """
    전략 스케줄러

    APScheduler 기반으로 전략 실행을 스케줄링합니다.
    - 장 마감 후 15:35 전략 실행
    - 휴장일 체크
    - 중복 실행 방지
    """

    def __init__(self):
        """초기화"""
        self.is_running = False
        self.scheduler = None
        self._execution_lock = asyncio.Lock()
        self._last_execution: dict[int, datetime] = {}

    async def start(self) -> None:
        """스케줄러 시작"""
        if self.is_running:
            logger.warning("[Scheduler] Already running")
            return

        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
            from apscheduler.triggers.cron import CronTrigger

            self.scheduler = AsyncIOScheduler(timezone=KST)

            # 장 마감 후 전략 실행 (월~금 15:35)
            self.scheduler.add_job(
                self._execute_strategies_job,
                CronTrigger(
                    day_of_week="mon-fri",
                    hour=15,
                    minute=35,
                    timezone=KST,
                ),
                id="daily_strategy_execution",
                name="Daily Strategy Execution",
                replace_existing=True,
            )

            # 유니버스 갱신 (토요일 10:00)
            self.scheduler.add_job(
                self._refresh_universe_job,
                CronTrigger(
                    day_of_week="sat",
                    hour=10,
                    minute=0,
                    timezone=KST,
                ),
                id="weekly_universe_refresh",
                name="Weekly Universe Refresh",
                replace_existing=True,
            )

            self.scheduler.start()
            self.is_running = True
            logger.info("[Scheduler] Strategy scheduler started")

        except ImportError:
            logger.warning(
                "[Scheduler] APScheduler not installed. "
                "Run: uv add apscheduler"
            )
        except Exception as e:
            logger.error(f"[Scheduler] Failed to start: {e}")

    async def stop(self) -> None:
        """스케줄러 중지"""
        if self.scheduler and self.is_running:
            self.scheduler.shutdown(wait=False)
            self.is_running = False
            logger.info("[Scheduler] Strategy scheduler stopped")

    async def _execute_strategies_job(self) -> None:
        """전략 실행 작업"""
        logger.info("[Scheduler] Starting daily strategy execution...")

        # 휴장일 체크
        if await self._is_holiday():
            logger.info("[Scheduler] Market is closed today. Skipping execution.")
            return

        # 중복 실행 방지
        if self._execution_lock.locked():
            logger.warning("[Scheduler] Execution already in progress. Skipping.")
            return

        async with self._execution_lock:
            try:
                async for session in get_async_session():
                    strategy_repo = StrategyRepository(session)
                    active_strategies = await strategy_repo.get_active_strategies()

                    if not active_strategies:
                        logger.info("[Scheduler] No active strategies found.")
                        return

                    kis_client = KISAPIClient()
                    engine = GoldenCrossEngine(session, kis_client)

                    for strategy in active_strategies:
                        # 골든크로스 전략만 실행
                        if strategy.strategy_type != "golden_cross":
                            continue

                        try:
                            # 오늘 이미 실행한 경우 스킵 (DB 기반 + 인메모리 백업)
                            if self._already_executed_today_from_db(strategy):
                                logger.info(
                                    f"[Scheduler] Strategy {strategy.id} already executed today (DB check)."
                                )
                                continue
                            if self._already_executed_today_in_memory(strategy.id):
                                logger.info(
                                    f"[Scheduler] Strategy {strategy.id} already executed today (memory check)."
                                )
                                continue

                            logger.info(
                                f"[Scheduler] Executing strategy {strategy.id}: {strategy.name}"
                            )

                            result = await engine.execute(
                                strategy_id=strategy.id,
                                dry_run=False,
                            )

                            self._last_execution[strategy.id] = datetime.now(KST)

                            logger.info(
                                f"[Scheduler] Strategy {strategy.id} completed: "
                                f"Buy={result.buy_signals}, Sell={result.sell_signals}, "
                                f"Orders={result.orders_created}"
                            )

                            if result.errors:
                                for error in result.errors:
                                    logger.error(f"[Scheduler] Error: {error}")

                        except Exception as e:
                            logger.exception(
                                f"[Scheduler] Strategy {strategy.id} execution failed: {e}"
                            )

            except Exception as e:
                logger.exception(f"[Scheduler] Strategy execution job failed: {e}")

    async def _refresh_universe_job(self) -> None:
        """유니버스 갱신 작업"""
        logger.info("[Scheduler] Starting weekly universe refresh...")

        try:
            # TODO: KIS API에서 종목 정보 수집 및 유니버스 갱신
            # 현재는 로그만 기록
            logger.info("[Scheduler] Universe refresh not implemented yet.")
        except Exception as e:
            logger.exception(f"[Scheduler] Universe refresh failed: {e}")

    async def _is_holiday(self) -> bool:
        """휴장일 체크"""
        try:
            kis_client = KISAPIClient()
            market_data_service = MarketDataService(kis_client)

            # is_holiday 메서드가 있는 경우 사용
            if hasattr(market_data_service, "is_holiday"):
                return await market_data_service.is_holiday()

            # 없으면 주말 체크만
            today = datetime.now(KST)
            return today.weekday() >= 5  # 토, 일

        except Exception as e:
            logger.warning(f"[Scheduler] Holiday check failed: {e}")
            # 실패 시 실행 진행
            return False

    def _already_executed_today_in_memory(self, strategy_id: int) -> bool:
        """오늘 이미 실행 여부 체크 (인메모리 - 백업용)"""
        if strategy_id not in self._last_execution:
            return False

        last_exec = self._last_execution[strategy_id]
        today = datetime.now(KST).date()
        return last_exec.date() == today

    def _already_executed_today_from_db(self, strategy) -> bool:
        """오늘 이미 실행 여부 체크 (DB 기반 - 멀티 워커 안전)"""
        if not strategy.last_executed_at:
            return False

        # DB의 last_executed_at는 timezone-aware datetime일 수 있음
        last_exec = strategy.last_executed_at
        if last_exec.tzinfo is None:
            # naive datetime인 경우 KST로 가정
            last_exec = last_exec.replace(tzinfo=KST)

        today = datetime.now(KST).date()
        return last_exec.date() == today

    async def execute_now(
        self, strategy_id: int, dry_run: bool = True, force: bool = False
    ) -> dict:
        """
        수동 실행

        Args:
            strategy_id: 전략 ID
            dry_run: Dry Run 모드
            force: 락 무시 여부

        Returns:
            dict: 실행 결과
        """
        if not force and self._execution_lock.locked():
            return {
                "success": False,
                "error": "Execution already in progress",
            }

        if force:
            return await self._execute_now(strategy_id, dry_run)

        async with self._execution_lock:
            return await self._execute_now(strategy_id, dry_run)

    async def _execute_now(self, strategy_id: int, dry_run: bool) -> dict:
        """수동 실행 실제 처리"""
        try:
            async for session in get_async_session():
                kis_client = KISAPIClient()
                engine = GoldenCrossEngine(session, kis_client)

                result = await engine.execute(
                    strategy_id=strategy_id,
                    dry_run=dry_run,
                )

                if not dry_run:
                    self._last_execution[strategy_id] = datetime.now(KST)

                return {
                    "success": True,
                    "result": result.model_dump(),
                }

        except Exception as e:
            logger.exception(f"[Scheduler] Manual execution failed: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    def get_status(self) -> dict:
        """스케줄러 상태 조회"""
        jobs = []
        if self.scheduler:
            for job in self.scheduler.get_jobs():
                jobs.append({
                    "id": job.id,
                    "name": job.name,
                    "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                })

        return {
            "is_running": self.is_running,
            "jobs": jobs,
            "last_executions": {
                str(k): v.isoformat()
                for k, v in self._last_execution.items()
            },
        }


# 싱글톤 인스턴스
_scheduler_instance: StrategyScheduler | None = None


def get_strategy_scheduler() -> StrategyScheduler:
    """
    StrategyScheduler 싱글톤 인스턴스 반환

    Returns:
        StrategyScheduler: 스케줄러 인스턴스
    """
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = StrategyScheduler()
    return _scheduler_instance
