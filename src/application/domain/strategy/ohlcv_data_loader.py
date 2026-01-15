# -*- coding: utf-8 -*-
"""
OHLCV Data Loader - 공통 OHLCV 데이터 로딩 모듈

DB 캐시 우선 조회 + 증분 업데이트 전략:
1. 캐시에 충분한 데이터가 있으면 캐시 사용
2. 캐시가 stale하면 누락된 최신 데이터만 API 호출 (chunking 지원)
3. 캐시가 없거나 부족하면 전체 데이터 요청 (2회 호출)
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.cache.redis_client import get_redis_client
from src.adapters.database.repositories.ohlcv_repository import OHLCVRepository
from src.adapters.external.kis_api.client import get_kis_client
from src.application.domain.market_data.service import MarketDataService


logger = logging.getLogger(__name__)

# KIS API 단일 호출 최대 조회 기간 (일)
MAX_API_DAYS_PER_CALL = 100


def normalize_timestamp(dt: datetime) -> datetime:
    """
    타임스탬프를 UTC timezone-aware로 정규화

    KIS API는 KST 날짜만 반환 (시간 정보 없음)하므로
    일봉 데이터는 날짜만 의미 있음. UTC로 통일하여
    tz-aware와 tz-naive 혼합 시 발생하는 비교 오류를 방지.

    Args:
        dt: 정규화할 datetime

    Returns:
        datetime: UTC timezone-aware datetime
    """
    if dt.tzinfo is None:
        # tz-naive → UTC로 가정
        return dt.replace(tzinfo=timezone.utc)
    # 이미 tz-aware → UTC로 변환
    return dt.astimezone(timezone.utc)


def normalize_df_timestamps(df: pd.DataFrame) -> pd.DataFrame:
    """
    DataFrame의 timestamp 컬럼을 UTC로 정규화

    Args:
        df: timestamp 컬럼이 있는 DataFrame

    Returns:
        pd.DataFrame: timestamp가 UTC로 정규화된 DataFrame
    """
    if df.empty or "timestamp" not in df.columns:
        return df

    df = df.copy()
    # pandas timestamp를 UTC로 변환
    if df["timestamp"].dt.tz is None:
        # tz-naive → UTC로 localize
        df["timestamp"] = df["timestamp"].dt.tz_localize("UTC")
    else:
        # tz-aware → UTC로 변환
        df["timestamp"] = df["timestamp"].dt.tz_convert("UTC")
    return df


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
        cache_freshness_days: int = 1,
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        """
        OHLCV 데이터를 DataFrame으로 로딩 (증분 업데이트 지원)

        증분 업데이트 전략:
        1. DB 캐시에서 기존 데이터 조회
        2. 캐시가 min_candles 이상이면:
           - 최신 날짜 확인
           - 신선하면 (≤cache_freshness_days) 캐시 그대로 반환
           - stale하면 누락된 최근 데이터만 API 호출 (chunking 지원)
        3. 캐시가 부족하면 전체 데이터 요청 (2회 호출)

        Args:
            symbol: 종목코드
            days: 조회 기간 (일), 기본 240일
            interval: 캔들 간격, 기본 "1d"
            min_candles: 최소 필요 캔들 수, 기본 165
            cache_freshness_days: 캐시 유효 기간 (일), 기본 1일.
                장 마감 후 스캔 시 1일, 주말에는 3일 권장.
            force_refresh: True면 캐시 신선도와 관계없이 증분 업데이트 시도

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
            force_refresh=force_refresh,
        )
        return result.df

    async def load_ohlcv_with_stats(
        self,
        symbol: str,
        days: int = 240,
        interval: str = "1d",
        min_candles: int = 165,
        cache_freshness_days: int = 1,
        force_refresh: bool = False,
    ) -> LoadResult:
        """
        OHLCV 데이터를 DataFrame으로 로딩 (통계 포함)

        Args:
            symbol: 종목코드
            days: 조회 기간 (일)
            interval: 캔들 간격
            min_candles: 최소 필요 캔들 수
            cache_freshness_days: 캐시 유효 기간 (일), 기본 1일
            force_refresh: True면 캐시 신선도와 관계없이 증분 업데이트 시도

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

        # force_refresh가 True면 fresh 상태도 stale로 처리
        cache_status = cache_result["status"]
        if force_refresh and cache_status == "fresh":
            cache_status = "stale"
            logger.debug(f"[OHLCVLoader] {symbol}: Force refresh - treating cache as stale")

        if cache_status == "fresh":
            # 캐시 완전 히트
            df = cache_result["df"]
            load_type = LoadType.CACHE_HIT
            logger.debug(f"[OHLCVLoader] {symbol}: Cache hit ({len(df) if df is not None else 0} candles)")

        elif cache_status == "stale" and cache_result["df"] is not None:
            # 증분 업데이트
            cached_df = cache_result["df"]
            latest = cache_result["latest"]

            incremental_df, new_count, inc_api_calls = await self._incremental_update(
                symbol=symbol,
                cached_df=cached_df,
                last_cached_date=latest,
                end_date=end_date,
                interval=interval,
            )

            if incremental_df is not None:
                df = incremental_df
                load_type = LoadType.INCREMENTAL
                api_calls = inc_api_calls
                new_candles = new_count
                logger.debug(
                    f"[OHLCVLoader] {symbol}: Incremental update "
                    f"(+{new_count} candles, {inc_api_calls} API calls)"
                )
            else:
                # 증분 업데이트 실패 시 전체 로딩
                df, full_api_calls = await self._load_from_api(
                    symbol=symbol,
                    start_date=start_date,
                    end_date=end_date,
                    interval=interval,
                )
                load_type = LoadType.FULL_LOAD
                api_calls = inc_api_calls + full_api_calls

        else:
            # 전체 로딩 (캐시 없음 또는 부족)
            df, full_api_calls = await self._load_from_api(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                interval=interval,
            )
            load_type = LoadType.FULL_LOAD
            api_calls = full_api_calls
            if df is not None:
                logger.debug(
                    f"[OHLCVLoader] {symbol}: Full load "
                    f"({len(df)} candles, {full_api_calls} API calls)"
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

            # DataFrame 타임존 정규화
            cached_df = normalize_df_timestamps(cached_df)

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
    ) -> tuple[pd.DataFrame | None, int, int]:
        """
        캐시된 데이터에 최신 데이터를 증분 추가

        오래된 캐시의 경우 MAX_API_DAYS_PER_CALL 단위로 chunking하여
        API 기간 제한을 준수합니다.

        Args:
            symbol: 종목코드
            cached_df: 기존 캐시 데이터
            last_cached_date: 캐시의 최신 날짜
            end_date: 요청 종료일
            interval: 캔들 간격

        Returns:
            tuple: (병합된 DataFrame, 새로 추가된 캔들 수, API 호출 횟수)
        """
        # 타임존 정규화
        last_cached_date = normalize_timestamp(last_cached_date)
        end_date = normalize_timestamp(end_date)

        # 이미 최신이면 캐시 그대로 반환
        days_gap = (end_date - last_cached_date).days
        if days_gap <= 1:
            return cached_df, 0, 0

        # 캐시된 DataFrame 타임존 정규화
        cached_df = normalize_df_timestamps(cached_df)

        market_data_service = await self._get_market_data_service()

        all_new_candles: list = []
        api_calls = 0

        try:
            # 누락 기간을 MAX_API_DAYS_PER_CALL 단위로 분할
            fetch_start = last_cached_date + timedelta(days=1)

            while fetch_start < end_date:
                # chunk 종료일 계산
                chunk_end = min(
                    fetch_start + timedelta(days=MAX_API_DAYS_PER_CALL),
                    end_date,
                )

                chart_data = await market_data_service.get_chart_data(
                    symbol=symbol,
                    interval=interval,
                    start_date=fetch_start,
                    end_date=chunk_end,
                )
                api_calls += 1

                if chart_data.candles:
                    all_new_candles.extend(chart_data.candles)

                # 다음 chunk로 이동
                fetch_start = chunk_end + timedelta(days=1)

            if not all_new_candles:
                # 신규 데이터 없음 (주말/휴일 등)
                return cached_df, 0, api_calls

            # 중복 제거 (API 응답에 중복 캔들이 있을 수 있음)
            candles_by_date = {c.timestamp: c for c in all_new_candles}
            unique_candles = list(candles_by_date.values())
            new_count = len(unique_candles)

            # 신규 데이터 DataFrame 변환 (타임존 정규화 포함)
            new_df = pd.DataFrame(
                [
                    {
                        "timestamp": normalize_timestamp(c.timestamp),
                        "open": float(c.open),
                        "high": float(c.high),
                        "low": float(c.low),
                        "close": float(c.close),
                        "volume": int(c.volume),
                    }
                    for c in unique_candles
                ]
            )
            new_df = normalize_df_timestamps(new_df)

            # 병합 및 중복 제거
            merged_df = pd.concat([cached_df, new_df], ignore_index=True)
            merged_df = (
                merged_df.drop_duplicates(subset=["timestamp"])
                .sort_values("timestamp")
                .reset_index(drop=True)
            )

            # 신규 데이터 DB 저장
            await self._cache_to_db(symbol, unique_candles, interval)

            return merged_df, new_count, api_calls

        except Exception as e:
            logger.warning(f"[OHLCVLoader] Incremental update failed for {symbol}: {e}")
            return None, 0, api_calls

    async def _load_from_api(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        interval: str,
    ) -> tuple[pd.DataFrame | None, int]:
        """
        KIS API에서 데이터 로딩 (요청 기간을 MAX_API_DAYS_PER_CALL 단위로 chunking)

        Returns:
            tuple: (DataFrame, API 호출 횟수)
        """
        market_data_service = await self._get_market_data_service()
        all_candles: list = []
        api_calls = 0

        # 타임존 정규화
        start_date = normalize_timestamp(start_date)
        end_date = normalize_timestamp(end_date)

        try:
            # 전체 기간을 MAX_API_DAYS_PER_CALL 단위로 분할하여 역순으로 조회
            # (최신 데이터부터 과거로)
            chunk_end = end_date

            while chunk_end > start_date:
                chunk_start = max(
                    chunk_end - timedelta(days=MAX_API_DAYS_PER_CALL),
                    start_date,
                )

                chart_data = await market_data_service.get_chart_data(
                    symbol=symbol,
                    interval=interval,
                    start_date=chunk_start,
                    end_date=chunk_end,
                )
                api_calls += 1

                if chart_data.candles:
                    all_candles.extend(chart_data.candles)

                # 다음 chunk로 이동 (과거 방향)
                chunk_end = chunk_start - timedelta(days=1)

        except Exception as e:
            logger.warning(f"[OHLCVLoader] API call failed for {symbol}: {e}")
            return None, api_calls

        if not all_candles:
            logger.debug(f"[OHLCVLoader] {symbol}: No candle data from API")
            return None, api_calls

        # 중복 제거 및 정렬
        candles_by_date = {c.timestamp: c for c in all_candles}
        all_candles = sorted(candles_by_date.values(), key=lambda c: c.timestamp)

        # DB 캐싱
        await self._cache_to_db(symbol, all_candles, interval)

        # DataFrame 변환 (타임존 정규화 포함)
        df = pd.DataFrame(
            [
                {
                    "timestamp": normalize_timestamp(c.timestamp),
                    "open": float(c.open),
                    "high": float(c.high),
                    "low": float(c.low),
                    "close": float(c.close),
                    "volume": int(c.volume),
                }
                for c in all_candles
            ]
        )
        df = normalize_df_timestamps(df)

        return df, api_calls

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
