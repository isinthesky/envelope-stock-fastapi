# -*- coding: utf-8 -*-
"""
OHLCV Warmup Service - OHLCV 캐시 워밍업 및 프리페칭

다중 종목 배치 워밍업, 증분 업데이트, 스마트 로딩 등
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.database.repositories.ohlcv_repository import OHLCVRepository
from src.adapters.database.repositories.stock_universe_repository import (
    StockUniverseRepository,
)
from src.application.domain.ohlcv.core_loader import OHLCVCoreLoader
from src.application.domain.ohlcv.dto import WarmupRequestDTO, WarmupResultDTO
from src.settings.config import settings

logger = logging.getLogger(__name__)


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
        self.core_loader = OHLCVCoreLoader(session)

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
        start_time = time.time()

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

        # 세마포어로 동시성 제어
        semaphore = asyncio.Semaphore(concurrency)

        async def warmup_one(symbol: str) -> tuple[str, bool, int, int, str | None]:
            """단일 종목 워밍업"""
            async with semaphore:
                try:
                    candles_count, api_calls = await self._warmup_symbol(
                        symbol=symbol,
                        days=request.days,
                        interval=request.interval,
                        force_refresh=request.force_refresh,
                    )

                    if api_calls == 0:
                        # 스킵됨 (이미 캐시됨)
                        return symbol, True, 0, 0, None
                    else:
                        return symbol, True, candles_count, api_calls, None

                except Exception as e:
                    logger.warning(f"[WarmupService] Failed to warmup {symbol}: {e}")
                    return symbol, False, 0, 0, str(e)

        # 병렬 실행
        tasks = [warmup_one(symbol) for symbol in request.symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for res in results:
            if isinstance(res, Exception):
                result.failed_count += 1
                result.errors.append(str(res))
            else:
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

        result.duration_seconds = round(time.time() - start_time, 2)

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
        end_date = datetime.now(timezone.utc)
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

        # CoreLoader로 API 호출
        df, api_calls = await self.core_loader.load_from_api(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            interval=interval,
        )

        if df.empty:
            return 0, api_calls

        # DB 저장
        saved_count = await self.core_loader.cache_to_db(
            symbol=symbol,
            df=df,
            interval=interval,
        )
        await self.session.commit()

        logger.debug(
            f"[WarmupService] {symbol}: Cached {saved_count} candles ({api_calls} API calls)"
        )

        return saved_count, api_calls

    # ==================== 유니버스 워밍업 ====================

    async def warmup_universe(
        self,
        universe_ids: list[int] | None = None,
        days: int = 240,
        concurrency: int = 3,
    ) -> WarmupResultDTO:
        """
        유니버스 전체 종목 워밍업

        Args:
            universe_ids: 유니버스 ID 목록 (None이면 모든 활성 종목)
            days: 조회 기간
            concurrency: 동시 처리 수

        Returns:
            WarmupResultDTO: 워밍업 결과
        """
        universe_repo = StockUniverseRepository(self.session)

        if universe_ids:
            # 특정 유니버스의 종목
            symbols = []
            for universe_id in universe_ids:
                stocks = await universe_repo.get_stocks_by_universe(universe_id)
                symbols.extend([stock.symbol for stock in stocks])
        else:
            # 모든 활성 종목
            stocks = await universe_repo.get_all_active_stocks()
            symbols = [stock.symbol for stock in stocks]

        # 중복 제거
        symbols = list(set(symbols))

        if not symbols:
            return WarmupResultDTO(
                total_symbols=0,
                errors=["No symbols found in universe"],
            )

        request = WarmupRequestDTO(
            symbols=symbols,
            days=days,
            interval="1d",
        )

        return await self.warmup_symbols(request, concurrency)

    # ==================== 증분 업데이트 ====================

    async def update_stale_symbols(
        self,
        freshness_days: Optional[int] = None,
        concurrency: int = 3,
    ) -> WarmupResultDTO:
        """
        오래된 데이터 보유 종목 증분 업데이트

        캐시된 마지막 날짜 이후 ~ 오늘까지만 API 호출

        Args:
            freshness_days: 신선도 기준 (일), None이면 설정값 사용
            concurrency: 동시 처리 수

        Returns:
            WarmupResultDTO: 업데이트 결과
        """
        # 기본값 설정
        if freshness_days is None:
            freshness_days = settings.ohlcv_warmup_freshness_days

        start_time = time.time()

        # 오래된 데이터 보유 종목 조회
        stale_data = await self.ohlcv_repo.get_symbols_with_stale_data(
            freshness_days=freshness_days,
        )

        if not stale_data:
            return WarmupResultDTO(
                total_symbols=0,
                success_count=0,
                duration_seconds=round(time.time() - start_time, 2),
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

        semaphore = asyncio.Semaphore(concurrency)

        async def update_one(item: dict) -> tuple[str, bool, int, int, str | None]:
            """단일 종목 증분 업데이트"""
            async with semaphore:
                symbol = item["symbol"]
                latest_date = item["latest_date"]

                try:
                    candles, calls = await self._incremental_update(
                        symbol=symbol,
                        from_date=latest_date,
                    )
                    return symbol, True, candles, calls, None
                except Exception as e:
                    return symbol, False, 0, 0, str(e)

        tasks = [update_one(item) for item in stale_data]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for res in results:
            if isinstance(res, Exception):
                result.failed_count += 1
                result.errors.append(str(res))
            else:
                symbol, success, candles, calls, error = res
                if success:
                    result.success_count += 1
                    result.candles_cached += candles
                    result.api_calls_made += calls
                else:
                    result.failed_count += 1
                    if error:
                        result.errors.append(f"{symbol}: {error}")

        result.duration_seconds = round(time.time() - start_time, 2)

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
        # 타임존 정규화
        from src.application.domain.ohlcv.core_loader import normalize_timestamp
        from_date = normalize_timestamp(from_date)

        end_date = datetime.now(timezone.utc)

        # 이미 최신이면 업데이트 불필요
        if (end_date - from_date).days <= 1:
            return 0, 0

        # 캐시된 데이터 조회
        start_date = end_date - timedelta(days=365)  # 1년치 조회
        cached_df = await self.ohlcv_repo.get_candles_to_dataframe(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            interval=interval,
        )

        # CoreLoader로 증분 업데이트
        try:
            merged_df, new_candles, api_calls = await self.core_loader.incremental_update(
                symbol=symbol,
                cached_df=cached_df,
                last_cached_date=from_date,
                end_date=end_date,
                interval=interval,
            )

            if new_candles == 0:
                return 0, api_calls

            # 새 데이터만 DB 저장 (전체가 아닌 증분만)
            # merged_df에서 from_date 이후 데이터만 추출
            if not merged_df.empty:
                new_df = merged_df[merged_df["timestamp"] > from_date]
                saved_count = await self.core_loader.cache_to_db(
                    symbol=symbol,
                    df=new_df,
                    interval=interval,
                )
                await self.session.commit()
                return saved_count, api_calls

            return 0, api_calls

        except Exception as e:
            logger.warning(f"[WarmupService] Incremental update failed for {symbol}: {e}")
            raise

    # ==================== 스마트 로딩 ====================

    async def smart_load_ohlcv(
        self,
        symbol: str,
        days: int = 240,
        min_candles: int = 165,
        interval: str = "1d",
    ) -> "pd.DataFrame":
        """
        스마트 OHLCV 로딩

        1. DB 캐시 확인
        2. 결측 구간만 API 호출 (전체 재호출 아님)
        3. 병합 후 반환

        Args:
            symbol: 종목코드
            days: 조회 기간
            min_candles: 최소 필요 캔들 수
            interval: 캔들 간격

        Returns:
            pd.DataFrame: OHLCV DataFrame
        """
        import pandas as pd

        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        # 캐시 확인
        availability = await self.ohlcv_repo.check_data_availability(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            interval=interval,
        )

        if availability.get("is_complete") and availability.get("count", 0) >= min_candles:
            # 캐시에서 바로 반환
            df = await self.ohlcv_repo.get_candles_to_dataframe(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                interval=interval,
            )
            if len(df) >= min_candles:
                return df

        # 결측 구간 확인 후 워밍업
        await self._warmup_symbol(
            symbol=symbol,
            days=days,
            interval=interval,
            force_refresh=False,
        )

        # 다시 조회
        df = await self.ohlcv_repo.get_candles_to_dataframe(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            interval=interval,
        )

        if df.empty or len(df) < min_candles:
            raise ValueError(
                f"Insufficient data for {symbol}: need {min_candles} candles, got {len(df)}"
            )

        return df
