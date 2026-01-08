# -*- coding: utf-8 -*-
"""
OHLCV Data Loader - 공통 OHLCV 데이터 로딩 모듈

DB 캐시 우선 조회 후, 없으면 KIS API로 데이터 수집
"""

import logging
from datetime import datetime, timedelta

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.cache.redis_client import get_redis_client
from src.adapters.database.repositories.ohlcv_repository import OHLCVRepository
from src.adapters.external.kis_api.client import get_kis_client
from src.application.domain.market_data.service import MarketDataService


logger = logging.getLogger(__name__)


class OHLCVDataLoader:
    """
    OHLCV 데이터 로더

    DB 캐시와 KIS API를 조합하여 OHLCV 데이터를 로딩합니다.
    - DB 캐시 우선 조회
    - 캐시 미스 시 API 2회 호출로 데이터 수집
    - 수집된 데이터는 DB에 캐싱
    """

    def __init__(self, session: AsyncSession | None = None) -> None:
        """
        Args:
            session: Database Session (캐싱용, 없으면 API만 사용)
        """
        self.session = session
        self._market_data_service: MarketDataService | None = None

    async def _get_market_data_service(self) -> MarketDataService:
        """MarketDataService 인스턴스 반환 (Lazy 초기화)"""
        if self._market_data_service is None:
            kis_client = get_kis_client()
            redis_client = await get_redis_client()
            self._market_data_service = MarketDataService(kis_client, redis_client)
        return self._market_data_service

    async def load_ohlcv_dataframe(
        self,
        symbol: str,
        days: int = 240,
        interval: str = "1d",
        min_candles: int = 160,
        cache_freshness_days: int = 3,
    ) -> pd.DataFrame:
        """
        OHLCV 데이터를 DataFrame으로 로딩

        DB 캐시 우선 조회 후, 캐시 미스 시 API 2회 호출로 데이터 수집합니다.

        Args:
            symbol: 종목코드
            days: 조회 기간 (일), 기본 240일
            interval: 캔들 간격, 기본 "1d"
            min_candles: 최소 필요 캔들 수, 기본 160
            cache_freshness_days: 캐시 유효 기간 (일), 기본 3일

        Returns:
            pd.DataFrame: OHLCV 데이터프레임 (timestamp, open, high, low, close, volume)

        Raises:
            ValueError: 데이터가 부족한 경우
        """
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        df = await self._try_load_from_cache(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            interval=interval,
            min_candles=min_candles,
            cache_freshness_days=cache_freshness_days,
        )

        if df is None:
            df = await self._load_from_api(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                interval=interval,
            )

        if df is None or df.empty:
            raise ValueError(f"No candle data available for {symbol}")

        # 중복 제거 및 정렬
        df = (
            df.drop_duplicates(subset=["timestamp"])
            .sort_values("timestamp")
            .reset_index(drop=True)
        )

        candle_count = len(df)
        if candle_count < min_candles:
            raise ValueError(
                f"Insufficient data for {symbol}: need {min_candles} candles, got {candle_count}"
            )

        return df

    async def _try_load_from_cache(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        interval: str,
        min_candles: int,
        cache_freshness_days: int,
    ) -> pd.DataFrame | None:
        """DB 캐시에서 데이터 로딩 시도"""
        if not self.session:
            return None

        ohlcv_repo = OHLCVRepository(self.session)

        try:
            availability = await ohlcv_repo.check_data_availability(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                interval=interval,
            )

            count = availability.get("count", 0)
            latest = availability.get("latest")

            # 충분한 데이터가 있고, 최신 데이터가 신선한 경우
            if count >= min_candles and latest:
                if (end_date - latest) <= timedelta(days=cache_freshness_days):
                    cached_df = await ohlcv_repo.get_candles_to_dataframe(
                        symbol=symbol,
                        start_date=start_date,
                        end_date=end_date,
                        interval=interval,
                    )
                    if not cached_df.empty:
                        logger.debug(
                            f"[OHLCVLoader] {symbol}: Cache hit ({len(cached_df)} candles)"
                        )
                        return cached_df

        except Exception as e:
            logger.warning(f"[OHLCVLoader] Cache check failed for {symbol}: {e}")

        return None

    async def _load_from_api(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        interval: str,
    ) -> pd.DataFrame | None:
        """KIS API에서 데이터 로딩 (2회 호출)"""
        market_data_service = await self._get_market_data_service()
        all_candles: list = []

        try:
            # 첫 번째 호출: 최근 120일
            mid_date = end_date - timedelta(days=120)
            chart_data1 = await market_data_service.get_chart_data(
                symbol=symbol,
                interval=interval,
                start_date=mid_date,
                end_date=end_date,
            )
            if chart_data1.candles:
                all_candles.extend(chart_data1.candles)

            # 두 번째 호출: 이전 120일
            if all_candles:
                earliest = min(c.timestamp for c in all_candles)
                chart_data2 = await market_data_service.get_chart_data(
                    symbol=symbol,
                    interval=interval,
                    start_date=earliest - timedelta(days=120),
                    end_date=earliest - timedelta(days=1),
                )
                if chart_data2.candles:
                    all_candles.extend(chart_data2.candles)

        except Exception as e:
            logger.warning(f"[OHLCVLoader] API call failed for {symbol}: {e}")
            return None

        if not all_candles:
            logger.debug(f"[OHLCVLoader] {symbol}: No candle data from API")
            return None

        # 중복 제거 및 정렬
        candles_by_date = {c.timestamp: c for c in all_candles}
        all_candles = sorted(candles_by_date.values(), key=lambda c: c.timestamp)

        logger.debug(f"[OHLCVLoader] {symbol}: API loaded {len(all_candles)} candles")

        # DB 캐싱
        await self._cache_to_db(symbol, all_candles, interval)

        # DataFrame 변환
        df = pd.DataFrame(
            [
                {
                    "timestamp": c.timestamp,
                    "open": float(c.open),
                    "high": float(c.high),
                    "low": float(c.low),
                    "close": float(c.close),
                    "volume": int(c.volume),
                }
                for c in all_candles
            ]
        )

        return df

    async def _cache_to_db(
        self,
        symbol: str,
        candles: list,
        interval: str,
    ) -> None:
        """수집된 캔들 데이터를 DB에 캐싱"""
        if not self.session:
            return

        ohlcv_repo = OHLCVRepository(self.session)

        try:
            await ohlcv_repo.save_candles_bulk(
                symbol=symbol,
                candles=candles,
                interval=interval,
                source="kis",
            )
            await self.session.commit()
            logger.debug(f"[OHLCVLoader] {symbol}: Cached {len(candles)} candles to DB")
        except Exception as e:
            await self.session.rollback()
            logger.warning(f"[OHLCVLoader] Failed to cache {symbol} candles: {e}")
