# -*- coding: utf-8 -*-
"""
OHLCV Data Loader - 공통 OHLCV 데이터 로딩 모듈

DB 캐시 우선 조회 + 증분 업데이트 전략:
1. 캐시에 충분한 데이터가 있으면 캐시 사용
2. 캐시가 stale하면 누락된 최신 데이터만 API 호출 (1회)
3. 캐시가 없거나 부족하면 전체 데이터 요청 (2회 호출)
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.cache.redis_client import get_redis_client
from src.adapters.database.repositories.ohlcv_repository import OHLCVRepository
from src.adapters.external.kis_api.client import get_kis_client
from src.application.domain.market_data.service import MarketDataService


logger = logging.getLogger(__name__)


class LoadType(str, Enum):
    """데이터 로딩 유형"""
    CACHE_HIT = "cache_hit"           # 캐시 완전 히트
    INCREMENTAL = "incremental"       # 증분 업데이트 (1 API call)
    FULL_LOAD = "full_load"           # 전체 로딩 (2 API calls)


@dataclass
class LoadResult:
    """데이터 로딩 결과"""
    df: pd.DataFrame
    load_type: LoadType
    api_calls: int = 0
    new_candles: int = 0


class OHLCVDataLoader:
    """
    OHLCV 데이터 로더 (증분 업데이트 지원)

    DB 캐시와 KIS API를 조합하여 OHLCV 데이터를 로딩합니다.
    - DB 캐시 우선 조회
    - 캐시가 stale하면 누락된 최신 데이터만 API 호출 (증분 업데이트)
    - 캐시가 없거나 부족하면 전체 API 호출 (2회)
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
        min_candles: int = 165,
        cache_freshness_days: int = 7,
    ) -> pd.DataFrame:
        """
        OHLCV 데이터를 DataFrame으로 로딩 (증분 업데이트 지원)

        증분 업데이트 전략:
        1. DB 캐시에서 기존 데이터 조회
        2. 캐시가 min_candles 이상이면:
           - 최신 날짜 확인
           - 신선하면 (≤cache_freshness_days) 캐시 그대로 반환
           - stale하면 누락된 최근 데이터만 API 호출 (1회)
        3. 캐시가 부족하면 전체 데이터 요청 (기존 2회 호출)

        Args:
            symbol: 종목코드
            days: 조회 기간 (일), 기본 240일
            interval: 캔들 간격, 기본 "1d"
            min_candles: 최소 필요 캔들 수, 기본 165
            cache_freshness_days: 캐시 유효 기간 (일), 기본 7일

        Returns:
            pd.DataFrame: OHLCV 데이터프레임 (timestamp, open, high, low, close, volume)

        Raises:
            ValueError: 데이터가 부족한 경우
        """
        result = await self.load_ohlcv_with_stats(
            symbol=symbol,
            days=days,
            interval=interval,
            min_candles=min_candles,
            cache_freshness_days=cache_freshness_days,
        )
        return result.df

    async def load_ohlcv_with_stats(
        self,
        symbol: str,
        days: int = 240,
        interval: str = "1d",
        min_candles: int = 165,
        cache_freshness_days: int = 7,
    ) -> LoadResult:
        """
        OHLCV 데이터를 DataFrame으로 로딩 (통계 포함)

        Args:
            symbol: 종목코드
            days: 조회 기간 (일)
            interval: 캔들 간격
            min_candles: 최소 필요 캔들 수
            cache_freshness_days: 캐시 유효 기간 (일)

        Returns:
            LoadResult: DataFrame과 로딩 통계
        """
        # DB 타임스탬프가 timezone-aware이므로 UTC 사용
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=days)

        # 1. 캐시 상태 확인
        cache_result = await self._check_cache_status(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            interval=interval,
            min_candles=min_candles,
            cache_freshness_days=cache_freshness_days,
        )

        df: pd.DataFrame | None = None
        load_type = LoadType.FULL_LOAD
        api_calls = 0
        new_candles = 0

        if cache_result["status"] == "fresh":
            # 캐시 완전 히트
            df = cache_result["df"]
            load_type = LoadType.CACHE_HIT
            logger.debug(f"[OHLCVLoader] {symbol}: Cache hit ({len(df)} candles)")

        elif cache_result["status"] == "stale" and cache_result["df"] is not None:
            # 증분 업데이트
            cached_df = cache_result["df"]
            latest = cache_result["latest"]

            incremental_df, new_count = await self._incremental_update(
                symbol=symbol,
                cached_df=cached_df,
                last_cached_date=latest,
                end_date=end_date,
                interval=interval,
            )

            if incremental_df is not None:
                df = incremental_df
                load_type = LoadType.INCREMENTAL
                api_calls = 1
                new_candles = new_count
                logger.debug(
                    f"[OHLCVLoader] {symbol}: Incremental update (+{new_count} candles)"
                )
            else:
                # 증분 업데이트 실패 시 전체 로딩
                df = await self._load_from_api(
                    symbol=symbol,
                    start_date=start_date,
                    end_date=end_date,
                    interval=interval,
                )
                load_type = LoadType.FULL_LOAD
                api_calls = 2

        else:
            # 전체 로딩 (캐시 없음 또는 부족)
            df = await self._load_from_api(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                interval=interval,
            )
            load_type = LoadType.FULL_LOAD
            api_calls = 2
            if df is not None:
                logger.debug(f"[OHLCVLoader] {symbol}: Full load ({len(df)} candles)")

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

        return LoadResult(
            df=df,
            load_type=load_type,
            api_calls=api_calls,
            new_candles=new_candles,
        )

    async def _check_cache_status(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        interval: str,
        min_candles: int,
        cache_freshness_days: int,
    ) -> dict:
        """
        캐시 상태 확인

        Returns:
            dict with:
            - status: "fresh" | "stale" | "insufficient" | "none"
            - df: DataFrame | None (캐시 데이터)
            - latest: datetime | None (최신 캔들 날짜)
            - count: int (캐시 캔들 수)
        """
        if not self.session:
            return {"status": "none", "df": None, "latest": None, "count": 0}

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

            if count < min_candles:
                return {"status": "insufficient", "df": None, "latest": latest, "count": count}

            if not latest:
                return {"status": "none", "df": None, "latest": None, "count": 0}

            # latest가 timezone-naive인 경우 UTC로 변환
            if latest.tzinfo is None:
                latest = latest.replace(tzinfo=timezone.utc)

            # 캐시된 데이터 가져오기
            cached_df = await ohlcv_repo.get_candles_to_dataframe(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                interval=interval,
            )

            if cached_df.empty:
                return {"status": "none", "df": None, "latest": None, "count": 0}

            # 신선도 판단
            days_since_latest = (end_date - latest).days
            if days_since_latest <= cache_freshness_days:
                return {"status": "fresh", "df": cached_df, "latest": latest, "count": count}
            else:
                return {"status": "stale", "df": cached_df, "latest": latest, "count": count}

        except Exception as e:
            logger.warning(f"[OHLCVLoader] Cache check failed for {symbol}: {e}")
            return {"status": "none", "df": None, "latest": None, "count": 0}

    async def _incremental_update(
        self,
        symbol: str,
        cached_df: pd.DataFrame,
        last_cached_date: datetime,
        end_date: datetime,
        interval: str,
    ) -> tuple[pd.DataFrame | None, int]:
        """
        캐시된 데이터에 최신 데이터를 증분 추가

        Args:
            symbol: 종목코드
            cached_df: 기존 캐시 데이터
            last_cached_date: 캐시의 최신 날짜
            end_date: 요청 종료일
            interval: 캔들 간격

        Returns:
            tuple: (병합된 DataFrame, 새로 추가된 캔들 수)
        """
        # 이미 최신이면 캐시 그대로 반환
        if (end_date - last_cached_date).days <= 1:
            return cached_df, 0

        # 누락된 기간만 API 호출 (1회)
        fetch_start = last_cached_date + timedelta(days=1)

        market_data_service = await self._get_market_data_service()

        try:
            chart_data = await market_data_service.get_chart_data(
                symbol=symbol,
                interval=interval,
                start_date=fetch_start,
                end_date=end_date,
            )

            if not chart_data.candles:
                # 신규 데이터 없음 (주말/휴일 등)
                return cached_df, 0

            new_candles = chart_data.candles
            new_count = len(new_candles)

            # 신규 데이터 DataFrame 변환
            new_df = pd.DataFrame(
                [
                    {
                        "timestamp": c.timestamp,
                        "open": float(c.open),
                        "high": float(c.high),
                        "low": float(c.low),
                        "close": float(c.close),
                        "volume": int(c.volume),
                    }
                    for c in new_candles
                ]
            )

            # 병합 및 중복 제거
            merged_df = pd.concat([cached_df, new_df], ignore_index=True)
            merged_df = (
                merged_df.drop_duplicates(subset=["timestamp"])
                .sort_values("timestamp")
                .reset_index(drop=True)
            )

            # 신규 데이터 DB 저장
            await self._cache_to_db(symbol, new_candles, interval)

            return merged_df, new_count

        except Exception as e:
            logger.warning(f"[OHLCVLoader] Incremental update failed for {symbol}: {e}")
            return None, 0

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
