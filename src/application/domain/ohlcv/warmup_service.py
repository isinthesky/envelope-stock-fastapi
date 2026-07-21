# -*- coding: utf-8 -*-
"""
OHLCV Warmup Service - OHLCV 캐시 워밍업 및 프리페칭

다중 종목 배치 워밍업, 증분 업데이트, 스마트 로딩 등
"""

import asyncio
import logging
import time as pytime
from datetime import date, datetime, time as dt_time, timedelta
from zoneinfo import ZoneInfo

from src.application.domain.ohlcv.cache_manager import KOREA_HOLIDAYS


from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.cache.redis_client import get_redis_client
from src.adapters.database.connection import AsyncSessionLocal
from src.adapters.database.repositories.ohlcv_repository import OHLCVRepository
from src.adapters.external.kis_api.client import get_kis_client
from src.application.domain.market_data.service import MarketDataService
from src.application.domain.ohlcv.dto import WarmupRequestDTO, WarmupResultDTO

logger = logging.getLogger(__name__)

# 한국 시간대 (거래일/일봉 기준)
KST = ZoneInfo("Asia/Seoul")
MAX_API_DAYS_PER_CALL = 100

# NOTE(naive datetime 관례, 2026-07 검토 완료):
# 이 모듈의 naive datetime.now()는 "컨테이너 TZ=UTC" 전제에서 UTC 벽시계로 동작하며,
# 이는 저장/조회 관례와 일치한다:
#   - 캔들 timestamp는 KIS 응답(YYYYMMDD)을 naive 자정으로 파싱해 timestamptz에 저장
#     (asyncpg가 naive를 UTC로 해석 → "거래일 00:00 UTC 라벨")
#   - OHLCVRepository.check_data_availability 등도 naive를 UTC로 정규화(to_utc)해 비교
# KST/UTC 날짜 스큐(KST 00:00~09:00 = UTC 전일 15:00~24:00)가 실질 영향이 없는 이유:
#   - 이 경로를 실행하는 스케줄 잡은 전부 KST 09:20~16:00(=UTC 00:20~07:00)에 돌아
#     UTC 날짜 == KST 날짜인 시간대만 사용한다 (ohlcv/scheduler.py 16:00 update,
#     notification_scheduler BUY/SELL 슬롯 09:20/11:20/12:20/14:20)
#   - 스큐 창에 도는 08:00 warmup 잡은 datetime.now(KST) + warmup_symbol_until을 써서
#     이 모듈의 naive now()를 경유하지 않는다
#   - 스큐 창에서 수동 호출되더라도 end 경계가 "KST 어제"로 줄어들 뿐인데, KST 09:00
#     장 시작 전에는 당일 일봉이 존재하지 않으므로 조회 결과는 동일하다
# ⚠️ 위 근거는 전부 "컨테이너 TZ=UTC" 배포 전제에 의존한다. TZ를 바꾸면 naive 자정
# 파싱 → timestamptz 저장 라벨 자체가 이동해 증분 날짜 판단이 어긋날 수 있으므로,
# TZ 변경이나 aware 통일은 repo 저장 관례(UTC 자정 라벨)와 함께 별도 정비로만
# 진행할 것. 이 모듈 단독 변경은 금지.


def is_trading_day_kst(target: date) -> bool:
    """거래일 여부 (주말 + 간단 공휴일 캘린더 기반)"""
    if target.weekday() >= 5:
        return False
    return datetime(target.year, target.month, target.day) not in KOREA_HOLIDAYS


def previous_trading_day_kst(reference: date) -> date:
    """reference 날짜의 직전 거래일 반환

    예: 월요일 -> 지난 금요일
    """
    cur = reference
    while True:
        cur = cur - timedelta(days=1)
        if is_trading_day_kst(cur):
            return cur


def iter_date_chunks(
    start: datetime,
    end: datetime,
    max_days: int,
) -> list[tuple[datetime, datetime]]:
    """inclusive date chunk iterator with max_days cap per chunk."""
    if start > end:
        return []
    chunk_start = start
    chunk_span = timedelta(days=max_days - 1)
    chunks: list[tuple[datetime, datetime]] = []
    while chunk_start <= end:
        chunk_end = min(chunk_start + chunk_span, end)
        chunks.append((chunk_start, chunk_end))
        chunk_start = chunk_end + timedelta(days=1)
    return chunks



class OHLCVWarmupService:
    """
    OHLCV 캐시 워밍업 및 프리페칭 서비스
    """

    def __init__(self, session: AsyncSession) -> None:
        """
        Args:
            session: Database Session
        """
        self.session = session
        self.ohlcv_repo = OHLCVRepository(session)
        self._market_data_service: MarketDataService | None = None

    async def _get_market_data_service(self) -> MarketDataService:
        """MarketDataService 인스턴스 반환 (Lazy 초기화)"""
        if self._market_data_service is None:
            kis_client = get_kis_client()
            redis_client = await get_redis_client()
            self._market_data_service = MarketDataService(kis_client, redis_client)
        return self._market_data_service

    # ==================== 배치 워밍업 ====================

    async def warmup_symbols(
        self,
        request: WarmupRequestDTO,
        concurrency: int = 3,
    ) -> WarmupResultDTO:
        """
        다중 종목 캐시 워밍업

        동시성 제어로 API 레이트 리밋을 준수하며 다중 종목을 워밍업

        Args:
            request: 워밍업 요청
            concurrency: 동시 처리 수

        Returns:
            WarmupResultDTO: 워밍업 결과
        """
        start_time = pytime.time()

        result = WarmupResultDTO(
            total_symbols=len(request.symbols),
            success_count=0,
            failed_count=0,
            skipped_count=0,
            api_calls_made=0,
            candles_cached=0,
            errors=[],
        )

        if not request.symbols:
            return result

        queue: asyncio.Queue[str] = asyncio.Queue()
        for symbol in request.symbols:
            queue.put_nowait(symbol)

        async def worker() -> list[tuple[str, bool, int, int, str | None]]:
            worker_results: list[tuple[str, bool, int, int, str | None]] = []
            async with AsyncSessionLocal() as worker_session:
                service = OHLCVWarmupService(worker_session)
                while True:
                    try:
                        symbol = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break

                    try:
                        candles_count, api_calls = await service._warmup_symbol(
                            symbol=symbol,
                            days=request.days,
                            interval=request.interval,
                            force_refresh=request.force_refresh,
                        )

                        if api_calls == 0:
                            # 스킵됨 (이미 캐시됨)
                            worker_results.append((symbol, True, 0, 0, None))
                        else:
                            worker_results.append((symbol, True, candles_count, api_calls, None))

                    except Exception as e:
                        await worker_session.rollback()
                        logger.warning(f"[WarmupService] Failed to warmup {symbol}: {e}")
                        worker_results.append((symbol, False, 0, 0, str(e)))
                    finally:
                        queue.task_done()

            return worker_results

        worker_count = min(concurrency, len(request.symbols))
        tasks = [asyncio.create_task(worker()) for _ in range(worker_count)]
        results_nested = await asyncio.gather(*tasks, return_exceptions=True)
        results: list[tuple[str, bool, int, int, str | None]] = []
        for res in results_nested:
            if isinstance(res, Exception):
                result.failed_count += 1
                result.errors.append(str(res))
            else:
                results.extend(res)

        for res in results:
            symbol, success, candles, calls, error = res
            if success:
                if calls == 0:
                    result.skipped_count += 1
                else:
                    result.success_count += 1
                    result.candles_cached += candles
                    result.api_calls_made += calls
            else:
                result.failed_count += 1
                if error:
                    result.errors.append(f"{symbol}: {error}")

        result.duration_seconds = round(pytime.time() - start_time, 2)

        logger.info(
            f"[WarmupService] Warmup completed: "
            f"{result.success_count} success, {result.skipped_count} skipped, "
            f"{result.failed_count} failed, {result.api_calls_made} API calls, "
            f"{result.duration_seconds}s"
        )

        return result

    async def _warmup_symbol(
        self,
        symbol: str,
        days: int,
        interval: str,
        force_refresh: bool,
    ) -> tuple[int, int]:
        """
        단일 종목 워밍업

        Returns:
            tuple[int, int]: (캐시된 캔들 수, API 호출 수)
        """
        # naive UTC now (모듈 상단 NOTE 참조) — repo/차트API 모두 naive-UTC 관례와 일치
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        # 캐시 확인 (force_refresh가 아닌 경우)
        if not force_refresh:
            availability = await self.ohlcv_repo.check_data_availability(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                interval=interval,
            )

            if availability.get("is_complete"):
                logger.debug(f"[WarmupService] {symbol}: Already cached, skipping")
                return 0, 0

        # API 호출로 데이터 수집
        market_data_service = await self._get_market_data_service()
        all_candles = []
        api_calls = 0

        try:
            for chunk_start, chunk_end in iter_date_chunks(
                start_date,
                end_date,
                MAX_API_DAYS_PER_CALL,
            ):
                chart_data = await market_data_service.get_chart_data(
                    symbol=symbol,
                    interval=interval,
                    start_date=chunk_start,
                    end_date=chunk_end,
                )
                api_calls += 1

                if chart_data.candles:
                    all_candles.extend(chart_data.candles)

        except Exception as e:
            logger.warning(f"[WarmupService] API call failed for {symbol}: {e}")
            raise

        if not all_candles:
            return 0, api_calls

        # 중복 제거
        candles_by_date = {c.timestamp: c for c in all_candles}
        unique_candles = list(candles_by_date.values())

        # DB 저장
        saved_count = await self.ohlcv_repo.save_candles_bulk(
            symbol=symbol,
            candles=unique_candles,
            interval=interval,
            source="kis",
        )
        await self.session.commit()

        logger.debug(
            f"[WarmupService] {symbol}: Cached {saved_count} candles ({api_calls} API calls)"
        )

        return saved_count, api_calls

    # ==================== 증분 업데이트 ====================

    async def update_stale_symbols(
        self,
        freshness_days: int = 3,
        concurrency: int = 3,
    ) -> WarmupResultDTO:
        """
        오래된 데이터 보유 종목 증분 업데이트

        캐시된 마지막 날짜 이후 ~ 오늘까지만 API 호출

        Args:
            freshness_days: 신선도 기준 (일)
            concurrency: 동시 처리 수

        Returns:
            WarmupResultDTO: 업데이트 결과
        """
        start_time = pytime.time()

        # 오래된 데이터 보유 종목 조회 (세션 분리)
        async with AsyncSessionLocal() as read_session:
            read_repo = OHLCVRepository(read_session)
            stale_data = await read_repo.get_symbols_with_stale_data(
                freshness_days=freshness_days,
            )

        if not stale_data:
            return WarmupResultDTO(
                total_symbols=0,
                success_count=0,
                duration_seconds=round(pytime.time() - start_time, 2),
            )

        result = WarmupResultDTO(
            total_symbols=len(stale_data),
            success_count=0,
            failed_count=0,
            skipped_count=0,
            api_calls_made=0,
            candles_cached=0,
            errors=[],
        )

        queue: asyncio.Queue[dict] = asyncio.Queue()
        for item in stale_data:
            queue.put_nowait(item)

        async def worker() -> list[tuple[str, bool, int, int, str | None]]:
            worker_results: list[tuple[str, bool, int, int, str | None]] = []
            async with AsyncSessionLocal() as worker_session:
                service = OHLCVWarmupService(worker_session)
                while True:
                    try:
                        item = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break

                    symbol = item["symbol"]
                    latest_date = item["latest_date"]

                    try:
                        candles, calls = await service._incremental_update(
                            symbol=symbol,
                            from_date=latest_date,
                        )
                        worker_results.append((symbol, True, candles, calls, None))
                    except Exception as e:
                        await worker_session.rollback()
                        worker_results.append((symbol, False, 0, 0, str(e)))
                    finally:
                        queue.task_done()

            return worker_results

        worker_count = min(concurrency, len(stale_data))
        tasks = [asyncio.create_task(worker()) for _ in range(worker_count)]
        results_nested = await asyncio.gather(*tasks, return_exceptions=True)
        results: list[tuple[str, bool, int, int, str | None]] = []
        for res in results_nested:
            if isinstance(res, Exception):
                result.failed_count += 1
                result.errors.append(str(res))
            else:
                results.extend(res)

        for res in results:
            symbol, success, candles, calls, error = res
            if success:
                result.success_count += 1
                result.candles_cached += candles
                result.api_calls_made += calls
            else:
                result.failed_count += 1
                if error:
                    result.errors.append(f"{symbol}: {error}")

        result.duration_seconds = round(pytime.time() - start_time, 2)

        logger.info(
            f"[WarmupService] Incremental update completed: "
            f"{result.success_count}/{result.total_symbols} updated, "
            f"{result.candles_cached} candles, {result.duration_seconds}s"
        )

        return result

    async def _incremental_update(
        self,
        symbol: str,
        from_date: datetime,
        interval: str = "1d",
    ) -> tuple[int, int]:
        """
        증분 업데이트 (마지막 날짜 이후만)

        Returns:
            tuple[int, int]: (캐시된 캔들 수, API 호출 수)
        """
        # 타임존 정규화 — DB timestamptz(거래일 00:00 UTC 라벨)를 naive로 벗겨 모듈 관례에 맞춤
        if from_date.tzinfo is not None:
            from_date = from_date.replace(tzinfo=None)

        # naive UTC now (모듈 상단 NOTE 참조)
        end_date = datetime.now()
        start_date = from_date + timedelta(days=1)  # 다음 날부터

        if start_date >= end_date:
            return 0, 0  # 업데이트 불필요

        market_data_service = await self._get_market_data_service()

        try:
            all_candles = []
            api_calls = 0

            for chunk_start, chunk_end in iter_date_chunks(
                start_date,
                end_date,
                MAX_API_DAYS_PER_CALL,
            ):
                chart_data = await market_data_service.get_chart_data(
                    symbol=symbol,
                    interval=interval,
                    start_date=chunk_start,
                    end_date=chunk_end,
                )
                api_calls += 1

                if chart_data.candles:
                    all_candles.extend(chart_data.candles)

            if not all_candles:
                return 0, api_calls

            # 중복 제거
            candles_by_date = {c.timestamp: c for c in all_candles}
            unique_candles = list(candles_by_date.values())

            # DB 저장
            saved_count = await self.ohlcv_repo.save_candles_bulk(
                symbol=symbol,
                candles=unique_candles,
                interval=interval,
                source="kis",
            )
            await self.session.commit()

            return saved_count, api_calls

        except Exception as e:
            logger.warning(f"[WarmupService] Incremental update failed for {symbol}: {e}")
            raise



    async def warmup_symbol_until(
        self,
        symbol: str,
        end_date: date,
        interval: str = "1d",
        days_if_empty: int = 450,
    ) -> tuple[int, int]:
        """어제까지(또는 지정 end_date까지) OHLCV 캐시를 채우는 워밍업

        - 캐시가 있으면: 최신 캔들 다음날 ~ end_date까지만 증분 호출
        - 캐시가 없으면: end_date 기준 days_if_empty만큼 과거부터 full load

        Returns:
            tuple[int, int]: (saved_candles_count, api_calls)
        """
        # end_date가 거래일이 아니면, 직전 거래일로 보정
        if not is_trading_day_kst(end_date):
            end_date = previous_trading_day_kst(end_date)

        latest_model = await self.ohlcv_repo.get_latest_candle(symbol=symbol, interval=interval)

        if latest_model is not None and getattr(latest_model, "timestamp", None) is not None:
            latest_date = latest_model.timestamp.date()
            if latest_date >= end_date:
                return 0, 0
            start_dt = datetime.combine(latest_date + timedelta(days=1), dt_time.min)
        else:
            start_dt = datetime.combine(end_date - timedelta(days=days_if_empty), dt_time.min)

        end_dt = datetime.combine(end_date, dt_time.min)
        if start_dt > end_dt:
            return 0, 0

        market_data_service = await self._get_market_data_service()

        all_candles = []
        api_calls = 0

        fetch_start = start_dt
        for chunk_start, chunk_end in iter_date_chunks(
            fetch_start,
            end_dt,
            MAX_API_DAYS_PER_CALL,
        ):
            chart = await market_data_service.get_chart_data(
                symbol=symbol,
                interval=interval,
                start_date=chunk_start,
                end_date=chunk_end,
                use_cache=False,
            )
            api_calls += 1

            if chart.candles:
                all_candles.extend(chart.candles)

        if not all_candles:
            return 0, api_calls

        # 중복 제거
        candles_by_ts = {c.timestamp: c for c in all_candles}
        unique_candles = list(candles_by_ts.values())

        saved_count = await self.ohlcv_repo.save_candles_bulk(
            symbol=symbol,
            candles=unique_candles,
            interval=interval,
            source="kis",
        )
        await self.session.commit()

        return saved_count, api_calls
