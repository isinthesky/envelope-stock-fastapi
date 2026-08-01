# -*- coding: utf-8 -*-
"""
OHLCV Core Loader - OHLCV 데이터 로딩 핵심 로직

OHLCVDataLoader와 WarmupService의 공통 로직을 통합
- 캐시 상태 확인
- API 호출 (동적 chunking)
- 증분 업데이트
- DB 캐싱
- 타임존 정규화
"""

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.database.repositories.ohlcv_repository import OHLCVRepository
from src.adapters.cache.redis_client import get_redis_client
from src.adapters.external.kis_api.client import get_kis_client
from src.application.domain.market_data.service import MarketDataService
from src.settings.config import settings

logger = logging.getLogger(__name__)


# ==================== 타임존 정규화 유틸리티 ====================

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


# ==================== Core Loader ====================

class OHLCVCoreLoader:
    """
    OHLCV 데이터 로딩 핵심 로직

    OHLCVDataLoader와 WarmupService에서 사용하는 공통 로직을 제공:
    - 캐시 상태 확인
    - API 호출 (동적 chunking)
    - 증분 업데이트
    - DB 캐싱
    """

    def __init__(self, session: Optional[AsyncSession] = None) -> None:
        """
        Args:
            session: Database Session (캐싱용, 없으면 API만 사용)
        """
        self.session = session
        self._market_data_service: Optional[MarketDataService] = None

    async def _get_market_data_service(self) -> MarketDataService:
        """MarketDataService 인스턴스 반환 (Lazy 초기화)"""
        if self._market_data_service is None:
            kis_client = get_kis_client()
            redis_client = await get_redis_client()
            self._market_data_service = MarketDataService(kis_client, redis_client)
        return self._market_data_service

    # ==================== 캐시 상태 확인 ====================

    async def check_cache_status(
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

        Args:
            symbol: 종목코드
            start_date: 시작일
            end_date: 종료일
            interval: 캔들 간격
            min_candles: 최소 필요 캔들 수
            cache_freshness_days: 캐시 유효 기간 (일)

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
            logger.warning(f"[CoreLoader] Cache check failed for {symbol}: {e}")
            return {"status": "none", "df": None, "latest": None, "count": 0}

    # ==================== API 호출 (동적 chunking) ====================

    async def load_from_api(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        interval: str = "1d",
    ) -> tuple[pd.DataFrame, int, int]:
        """
        KIS API로부터 OHLCV 데이터 로딩 (동적 chunking)

        Returns (df, api_calls, failed_chunks). failed_chunks>0이면 부분 실패로
        시계열에 갭이 있을 수 있으므로 호출측은 캐시 저장을 건너뛰는 것이 안전하다.

        요청 기간에 따라 API 호출 횟수를 동적으로 계산:
        - 100일 이하: 1회 호출
        - 100일 초과: 필요한 만큼 chunking

        Args:
            symbol: 종목코드
            start_date: 시작일
            end_date: 종료일
            interval: 캔들 간격

        Returns:
            tuple: (DataFrame, API 호출 횟수)
        """
        market_data = await self._get_market_data_service()

        # 요청 기간 계산
        days_requested = (end_date - start_date).days
        max_days = settings.ohlcv_max_api_days_per_call

        # 필요한 API 호출 횟수 계산 (start==end 단일일 요청도 최소 1회 보장)
        calls_needed = max(1, math.ceil(days_requested / max_days))

        all_candles = []
        api_calls = 0
        failed_chunks = 0  # 실패 청크 수(부분 실패 → 무음 갭 방지용으로 호출측에 반환)

        for i in range(calls_needed):
            # 각 청크의 시작/종료 계산
            chunk_end = end_date - timedelta(days=i * max_days)
            chunk_start = max(
                start_date,
                chunk_end - timedelta(days=max_days)
            )

            try:
                # get_chart_data는 datetime을 기대(_as_kst가 .tzinfo 접근).
                # .date()를 넘기면 'date' object has no attribute 'tzinfo'로 실패한다.
                chart_data = await market_data.get_chart_data(
                    symbol=symbol,
                    interval=interval,
                    start_date=chunk_start,
                    end_date=chunk_end,
                )

                if chart_data and chart_data.candles:
                    all_candles.extend(chart_data.candles)

            except Exception as e:
                failed_chunks += 1
                logger.error(
                    f"[CoreLoader] chunk {i+1}/{calls_needed} FAILED for {symbol} "
                    f"[{chunk_start:%Y%m%d}-{chunk_end:%Y%m%d}]: {e} (data hole risk)"
                )
            finally:
                # API 호출 시도는 성공/실패 여부와 관계없이 카운트
                api_calls += 1

        if not all_candles:
            logger.warning(f"[CoreLoader] No data from API for {symbol}")
            return pd.DataFrame(), api_calls, failed_chunks

        # DataFrame 변환
        df = pd.DataFrame([
            {
                "timestamp": candle.timestamp,
                "open": float(candle.open),
                "high": float(candle.high),
                "low": float(candle.low),
                "close": float(candle.close),
                "volume": candle.volume,
            }
            for candle in all_candles
        ])

        # 타임존 정규화 및 정렬
        df = normalize_df_timestamps(df)
        # 청크 경계 오버랩으로 생긴 중복 timestamp 제거(ON CONFLICT cardinality violation 방지)
        df = (
            df.sort_values("timestamp")
            .drop_duplicates(subset=["timestamp"], keep="last")
            .reset_index(drop=True)
        )

        logger.debug(
            f"[CoreLoader] Loaded {len(df)} candles for {symbol} ({api_calls} API calls)"
        )

        return df, api_calls, failed_chunks

    # ==================== 증분 업데이트 ====================

    async def incremental_update(
        self,
        symbol: str,
        cached_df: pd.DataFrame,
        last_cached_date: datetime,
        end_date: datetime,
        interval: str,
    ) -> tuple[Optional[pd.DataFrame], int, int, int]:
        """
        캐시된 데이터에 최신 데이터를 증분 추가

        오래된 캐시의 경우 settings.ohlcv_max_api_days_per_call 단위로 chunking하여
        API 기간 제한을 준수합니다.

        Args:
            symbol: 종목코드
            cached_df: 기존 캐시 데이터
            last_cached_date: 캐시의 최신 날짜
            end_date: 요청 종료일
            interval: 캔들 간격

        Returns:
            tuple: (병합된 DataFrame, 새 캔들 수, API 호출 횟수, 실패 청크 수)
            failed_chunks>0이면 갭 위험이 있어 호출측은 캐시 저장을 건너뛰어야 한다.
        """
        # 타임존 정규화
        last_cached_date = normalize_timestamp(last_cached_date)
        end_date = normalize_timestamp(end_date)

        # 이미 최신이면 캐시 그대로 반환
        days_gap = (end_date - last_cached_date).days
        if days_gap <= 1:
            return cached_df, 0, 0, 0

        # 증분 데이터 로딩
        increment_start = last_cached_date + timedelta(days=1)
        new_df, api_calls, failed_chunks = await self.load_from_api(
            symbol=symbol,
            start_date=increment_start,
            end_date=end_date,
            interval=interval,
        )

        if new_df.empty:
            return cached_df, 0, api_calls, failed_chunks

        # 기존 캐시와 병합
        merged_df = pd.concat([cached_df, new_df], ignore_index=True)
        merged_df = merged_df.drop_duplicates(subset=["timestamp"], keep="last")
        merged_df = merged_df.sort_values("timestamp").reset_index(drop=True)

        new_candles = len(new_df)

        logger.debug(
            f"[CoreLoader] Incremental update for {symbol}: "
            f"+{new_candles} candles ({api_calls} API calls)"
        )

        return merged_df, new_candles, api_calls, failed_chunks

    # ==================== DB 캐싱 ====================

    async def cache_to_db(
        self,
        symbol: str,
        df: pd.DataFrame,
        interval: str = "1d",
    ) -> int:
        """
        DataFrame을 DB에 캐싱

        Args:
            symbol: 종목코드
            df: 캐싱할 DataFrame
            interval: 캔들 간격

        Returns:
            int: 저장된 캔들 수
        """
        if not self.session or df.empty:
            return 0

        # NaN 가격/거래량 행 제외: Postgres numeric은 'NaN'을 받아 지표/백테스트를 오염시키고,
        # int(NaN volume)은 ValueError로 심볼 전체 저장을 실패(saved=0)시킨다.
        df = df.dropna(subset=["open", "high", "low", "close", "volume"])
        if df.empty:
            return 0

        ohlcv_repo = OHLCVRepository(self.session)

        # DataFrame → CandleDTO 변환
        from src.application.domain.market_data.dto import CandleDTO
        from decimal import Decimal

        candles = []
        for _, row in df.iterrows():
            candles.append(CandleDTO(
                timestamp=row["timestamp"].to_pydatetime() if hasattr(row["timestamp"], 'to_pydatetime') else row["timestamp"],
                open=Decimal(str(row["open"])),
                high=Decimal(str(row["high"])),
                low=Decimal(str(row["low"])),
                close=Decimal(str(row["close"])),
                volume=int(row["volume"]),
            ))

        # 배치 저장
        try:
            saved_count = await ohlcv_repo.save_candles_bulk(
                symbol=symbol,
                candles=candles,
                interval=interval,
            )

            logger.debug(f"[CoreLoader] Cached {saved_count} candles for {symbol}")
            return saved_count

        except Exception as e:
            logger.error(f"[CoreLoader] Failed to cache data for {symbol}: {e}")
            return 0
