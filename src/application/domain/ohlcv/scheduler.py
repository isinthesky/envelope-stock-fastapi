# -*- coding: utf-8 -*-
"""
OHLCV Cache Scheduler - OHLCV 캐시 정기 작업 스케줄러

매일 정해진 시간에 오래된 데이터 정리 및 증분 업데이트 수행
"""

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.adapters.database.connection import AsyncSessionLocal, get_async_session
from src.application.domain.ohlcv.cache_manager import OHLCVCacheManager
from src.application.domain.ohlcv.dto import CacheRetentionPolicyDTO
from src.application.domain.ohlcv.warmup_service import OHLCVWarmupService, previous_trading_day_kst
from src.adapters.database.repositories.stock_universe_repository import StockUniverseRepository

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")


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

        self._scheduler = AsyncIOScheduler(
            timezone="Asia/Seoul",
            job_defaults={
                # 이벤트 루프 지연으로 초 단위 지각 시에도 잡을 건너뛰지 않도록
                "coalesce": True,
                "misfire_grace_time": 300,
            },
        )

        # 매일 새벽 2시: 오래된 데이터 정리
        self._scheduler.add_job(
            self._cleanup_job,
            trigger=CronTrigger(hour=2, minute=0, timezone="Asia/Seoul"),
            id="ohlcv_cleanup",
            name="OHLCV Cache Cleanup",
            replace_existing=True,
        )

        # 매일 오전 8시: (거래일 기준) 어제까지 OHLCV 캐시 워밍업
        # - 주말/휴일은 직전 거래일로 자동 보정
        # - 전체 기간 재호출이 아니라 누락된 최신 구간만 호출
        self._scheduler.add_job(
            self._warmup_until_yesterday_job,
            trigger=CronTrigger(
                hour=8,
                minute=0,
                timezone="Asia/Seoul",
            ),
            id="ohlcv_warmup_until_yesterday",
            name="OHLCV Morning Warmup (until yesterday)",
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
                timezone="Asia/Seoul",
            ),
            id="ohlcv_update",
            name="OHLCV Incremental Update",
            replace_existing=True,
        )

        self._scheduler.start()
        self._is_running = True

        logger.info("[OHLCVScheduler] Started (cleanup: 02:00 daily, warmup: 08:00 daily, update: 16:00 weekdays)")

    async def stop(self) -> None:
        """스케줄러 중지"""
        if not self._is_running or not self._scheduler:
            return

        self._scheduler.shutdown(wait=False)
        self._scheduler = None
        self._is_running = False

        logger.info("[OHLCVScheduler] Stopped")


    async def _warmup_until_yesterday_job(self) -> None:
        # (거래일 기준) 어제까지 OHLCV 캐시 워밍업
        # - 매일 08:00
        # - 주말/휴일 포함하여 직전 거래일까지(대개 어제, 월요일이면 지난 금요일)
        # - 전체 기간 재호출이 아니라 누락된 최신 구간만 호출
        logger.info("[OHLCVScheduler] Starting morning warmup job (until yesterday)...")

        try:
            # NOTE: 서버/컨테이너 TZ가 KST가 아닐 수도 있으므로 명시적으로 KST 기준 날짜를 사용한다.
            today_kst = datetime.now(KST).date()
            end_date = previous_trading_day_kst(today_kst)

            # 스캔 대상 유니버스(최대 500) 심볼 목록 확보
            async with get_async_session() as session:
                universe_repo = StockUniverseRepository(session)
                stocks = await universe_repo.get_scan_stocks(
                    market=None,
                    include_etf=True,
                    limit=500,
                    session=session,
                )
                symbols = list({s.symbol for s in stocks if getattr(s, "symbol", None)})

            if not symbols:
                logger.info("[OHLCVScheduler] Morning warmup skipped: no symbols")
                return

            # 세션을 워커마다 분리 (AsyncSession 동시 사용 방지)
            concurrency = 3
            semaphore = asyncio.Semaphore(concurrency)
            work_queue: asyncio.Queue[str] = asyncio.Queue()
            for sym in symbols:
                work_queue.put_nowait(sym)

            async def worker() -> tuple[int, int, int, int]:
                w_saved = 0
                w_calls = 0
                w_success = 0
                w_failed = 0

                async with AsyncSessionLocal() as worker_session:
                    service = OHLCVWarmupService(worker_session)

                    while True:
                        try:
                            sym = work_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break

                        async with semaphore:
                            try:
                                saved, calls = await service.warmup_symbol_until(
                                    symbol=sym,
                                    end_date=end_date,
                                    interval="1d",
                                    days_if_empty=450,
                                )
                                w_saved += saved
                                w_calls += calls
                                w_success += 1
                            except Exception as e:
                                logger.warning(f"[OHLCVScheduler] Warmup failed {sym}: {e}")
                                w_failed += 1
                            finally:
                                work_queue.task_done()

                return w_saved, w_calls, w_success, w_failed

            workers = [asyncio.create_task(worker()) for _ in range(concurrency)]
            results = await asyncio.gather(*workers, return_exceptions=True)

            total_saved = 0
            total_calls = 0
            success = 0
            failed = 0

            for r in results:
                if isinstance(r, Exception):
                    failed += 1
                    continue
                w_saved, w_calls, w_success, w_failed = r
                total_saved += w_saved
                total_calls += w_calls
                success += w_success
                failed += w_failed

            logger.info(
                "[OHLCVScheduler] Morning warmup completed: "
                f"symbols={len(symbols)}, success={success}, failed={failed}, "
                f"saved={total_saved}, api_calls={total_calls}, end_date={end_date}"
            )

        except Exception as e:
            logger.error(f"[OHLCVScheduler] Morning warmup job failed: {e}", exc_info=True)

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
