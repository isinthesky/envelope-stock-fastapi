# -*- coding: utf-8 -*-
"""
OHLCV Cache Scheduler - OHLCV 캐시 정기 작업 스케줄러

매일 정해진 시간에 오래된 데이터 정리 및 증분 업데이트 수행
"""

import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.adapters.database.connection import get_async_session
from src.application.domain.ohlcv.cache_manager import OHLCVCacheManager
from src.application.domain.ohlcv.dto import CacheRetentionPolicyDTO
from src.application.domain.ohlcv.warmup_service import OHLCVWarmupService

logger = logging.getLogger(__name__)


class OHLCVCacheScheduler:
    """
    OHLCV 캐시 정기 작업 스케줄러

    정기 작업:
    - 02:00: 오래된 데이터 정리 (365일 이전)
    - 16:00: 장 마감 후 증분 업데이트 (당일 종가 확정 후)
    """

    def __init__(self) -> None:
        self._scheduler: AsyncIOScheduler | None = None
        self._is_running: bool = False

    @property
    def is_running(self) -> bool:
        """스케줄러 실행 상태"""
        return self._is_running

    async def start(self) -> None:
        """스케줄러 시작"""
        if self._is_running:
            logger.warning("[OHLCVScheduler] Already running")
            return

        self._scheduler = AsyncIOScheduler(timezone="Asia/Seoul")

        # 매일 새벽 2시: 오래된 데이터 정리
        self._scheduler.add_job(
            self._cleanup_job,
            trigger=CronTrigger(hour=2, minute=0),
            id="ohlcv_cleanup",
            name="OHLCV Cache Cleanup",
            replace_existing=True,
        )

        # 장 마감 후 (16:00): 증분 업데이트
        # 당일 종가 확정 후 캐시를 최신 상태로 유지
        # 평일만 실행 (월-금: day_of_week='mon-fri')
        self._scheduler.add_job(
            self._update_job,
            trigger=CronTrigger(
                day_of_week="mon-fri",
                hour=16,
                minute=0,
            ),
            id="ohlcv_update",
            name="OHLCV Incremental Update",
            replace_existing=True,
        )

        self._scheduler.start()
        self._is_running = True

        logger.info("[OHLCVScheduler] Started (cleanup: 02:00, update: 16:00 weekdays)")

    async def stop(self) -> None:
        """스케줄러 중지"""
        if not self._is_running or not self._scheduler:
            return

        self._scheduler.shutdown(wait=False)
        self._scheduler = None
        self._is_running = False

        logger.info("[OHLCVScheduler] Stopped")

    async def _cleanup_job(self) -> None:
        """오래된 데이터 정리 작업"""
        logger.info("[OHLCVScheduler] Starting cleanup job...")

        try:
            async with get_async_session() as session:
                manager = OHLCVCacheManager(session)
                policy = CacheRetentionPolicyDTO(
                    retention_days=365,
                    cleanup_batch_size=1000,
                )
                result = await manager.cleanup_old_data(policy, dry_run=False)

                logger.info(
                    f"[OHLCVScheduler] Cleanup completed: "
                    f"{result.deleted_count} records deleted, "
                    f"{len(result.symbols_affected)} symbols affected, "
                    f"{result.duration_seconds}s"
                )

        except Exception as e:
            logger.error(f"[OHLCVScheduler] Cleanup job failed: {e}", exc_info=True)

    async def _update_job(self) -> None:
        """증분 업데이트 작업"""
        logger.info("[OHLCVScheduler] Starting incremental update job...")

        try:
            async with get_async_session() as session:
                service = OHLCVWarmupService(session)
                result = await service.update_stale_symbols(
                    freshness_days=3,
                    concurrency=3,
                )

                logger.info(
                    f"[OHLCVScheduler] Update completed: "
                    f"{result.success_count}/{result.total_symbols} updated, "
                    f"{result.candles_cached} candles cached, "
                    f"{result.api_calls_made} API calls, "
                    f"{result.duration_seconds}s"
                )

        except Exception as e:
            logger.error(f"[OHLCVScheduler] Update job failed: {e}", exc_info=True)

    async def run_cleanup_now(self) -> dict:
        """수동 정리 작업 실행"""
        logger.info("[OHLCVScheduler] Manual cleanup triggered")

        try:
            async with get_async_session() as session:
                manager = OHLCVCacheManager(session)
                policy = CacheRetentionPolicyDTO(
                    retention_days=365,
                    cleanup_batch_size=1000,
                )
                result = await manager.cleanup_old_data(policy, dry_run=False)

                return {
                    "success": True,
                    "deleted_count": result.deleted_count,
                    "symbols_affected": len(result.symbols_affected),
                    "duration_seconds": result.duration_seconds,
                }

        except Exception as e:
            logger.error(f"[OHLCVScheduler] Manual cleanup failed: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def run_update_now(self) -> dict:
        """수동 업데이트 작업 실행"""
        logger.info("[OHLCVScheduler] Manual update triggered")

        try:
            async with get_async_session() as session:
                service = OHLCVWarmupService(session)
                result = await service.update_stale_symbols(
                    freshness_days=3,
                    concurrency=3,
                )

                return {
                    "success": True,
                    "updated_count": result.success_count,
                    "total_symbols": result.total_symbols,
                    "candles_cached": result.candles_cached,
                    "api_calls": result.api_calls_made,
                    "duration_seconds": result.duration_seconds,
                }

        except Exception as e:
            logger.error(f"[OHLCVScheduler] Manual update failed: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    def get_next_run_times(self) -> dict:
        """다음 실행 시간 조회"""
        if not self._scheduler:
            return {}

        jobs = {}
        for job in self._scheduler.get_jobs():
            jobs[job.id] = {
                "name": job.name,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            }

        return jobs


# 싱글톤 인스턴스
_ohlcv_scheduler: OHLCVCacheScheduler | None = None


def get_ohlcv_scheduler() -> OHLCVCacheScheduler:
    """OHLCV 캐시 스케줄러 싱글톤 인스턴스 반환"""
    global _ohlcv_scheduler
    if _ohlcv_scheduler is None:
        _ohlcv_scheduler = OHLCVCacheScheduler()
    return _ohlcv_scheduler
