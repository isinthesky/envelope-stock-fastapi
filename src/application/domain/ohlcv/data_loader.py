# -*- coding: utf-8 -*-
"""
OHLCV Data Loader - 전략/백테스트용 OHLCV 데이터 로딩

DB 캐시 우선 조회 + 증분 업데이트 전략:
1. 캐시에 충분한 데이터가 있으면 캐시 사용
2. 캐시가 stale하면 누락된 최신 데이터만 API 호출 (chunking 지원)
3. 캐시가 없거나 부족하면 전체 데이터 요청

OHLCVCoreLoader를 사용하여 핵심 로직을 공유합니다.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.domain.ohlcv.core_loader import OHLCVCoreLoader
from src.settings.config import settings

logger = logging.getLogger(__name__)


class LoadType(str, Enum):
    """데이터 로딩 유형"""
    CACHE_HIT = "cache_hit"           # 캐시 완전 히트
    INCREMENTAL = "incremental"       # 증분 업데이트
    FULL_LOAD = "full_load"           # 전체 로딩


@dataclass
class LoadResult:
    """데이터 로딩 결과"""
    df: pd.DataFrame
    load_type: LoadType
    api_calls: int = 0
    new_candles: int = 0


class OHLCVDataLoader:
    """
    OHLCV 데이터 로더 (전략/백테스트용)

    DB 캐시와 KIS API를 조합하여 OHLCV 데이터를 로딩합니다.
    OHLCVCoreLoader를 사용하여 핵심 로직을 공유합니다.
    """

    def __init__(self, session: Optional[AsyncSession] = None) -> None:
        """
        Args:
            session: Database Session (캐싱용, 없으면 API만 사용)
        """
        self.session = session
        self.core_loader = OHLCVCoreLoader(session)

    async def load_ohlcv_dataframe(
        self,
        symbol: str,
        days: int = 240,
        interval: str = "1d",
        min_candles: int = 165,
        cache_freshness_days: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        OHLCV 데이터를 DataFrame으로 로딩 (증분 업데이트 지원)

        증분 업데이트 전략:
        1. DB 캐시에서 기존 데이터 조회
        2. 캐시가 min_candles 이상이면:
           - 최신 날짜 확인
           - 신선하면 (≤cache_freshness_days) 캐시 그대로 반환
           - stale하면 누락된 최근 데이터만 API 호출 (chunking 지원)
        3. 캐시가 부족하면 전체 데이터 요청

        Args:
            symbol: 종목코드
            days: 조회 기간 (일), 기본 240일
            interval: 캔들 간격, 기본 "1d"
            min_candles: 최소 필요 캔들 수, 기본 165
            cache_freshness_days: 캐시 유효 기간 (일), 기본 1일.
                장 마감 후 스캔 시 1일, 주말에는 3일 권장.

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
        cache_freshness_days: Optional[int] = None,
    ) -> LoadResult:
        """
        OHLCV 데이터를 DataFrame으로 로딩 (통계 포함)

        Args:
            symbol: 종목코드
            days: 조회 기간 (일)
            interval: 캔들 간격
            min_candles: 최소 필요 캔들 수
            cache_freshness_days: 캐시 유효 기간 (일), None이면 설정값 사용

        Returns:
            LoadResult: DataFrame과 로딩 통계
        """
        # 기본값 설정
        if cache_freshness_days is None:
            cache_freshness_days = settings.ohlcv_cache_freshness_days

        # DB 타임스탬프가 timezone-aware이므로 UTC 사용
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=days)

        # 1. 캐시 상태 확인
        cache_result = await self.core_loader.check_cache_status(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            interval=interval,
            min_candles=min_candles,
            cache_freshness_days=cache_freshness_days,
        )

        df: Optional[pd.DataFrame] = None
        load_type = LoadType.FULL_LOAD
        api_calls = 0
        new_candles = 0
        failed_chunks = 0  # 부분 실패 시 캐시 저장을 건너뛰어 갭 영구화 방지

        if cache_result["status"] == "fresh":
            # 캐시 완전 히트
            df = cache_result["df"]
            load_type = LoadType.CACHE_HIT
            logger.debug(f"[OHLCVLoader] {symbol}: Cache hit ({len(df)} candles)")

        elif cache_result["status"] == "stale" and cache_result["df"] is not None:
            # 증분 업데이트
            cached_df = cache_result["df"]
            latest = cache_result["latest"]

            incremental_df, new_count, inc_api_calls, failed_chunks = await self.core_loader.incremental_update(
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
                df, full_api_calls, failed_chunks = await self.core_loader.load_from_api(
                    symbol=symbol,
                    start_date=start_date,
                    end_date=end_date,
                    interval=interval,
                )
                load_type = LoadType.FULL_LOAD
                api_calls = inc_api_calls + full_api_calls

        else:
            # 전체 로딩 (캐시 없음 또는 부족)
            df, full_api_calls, failed_chunks = await self.core_loader.load_from_api(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                interval=interval,
            )
            load_type = LoadType.FULL_LOAD
            api_calls = full_api_calls
            new_candles = len(df) if df is not None else 0

        # DB 캐싱 (새로운 데이터가 있고 세션이 있는 경우).
        # failed_chunks>0면 시계열에 갭이 있을 수 있어 저장을 건너뛴다(갭 영구화 방지, 다음 실행에 재시도).
        if (
            self.session
            and df is not None
            and not df.empty
            and load_type != LoadType.CACHE_HIT
            and failed_chunks == 0
        ):
            await self.core_loader.cache_to_db(
                symbol=symbol,
                df=df,
                interval=interval,
            )
            await self.session.commit()

        # 최소 캔들 수 검증
        if df is None or df.empty or len(df) < min_candles:
            actual_count = 0 if df is None or df.empty else len(df)
            raise ValueError(
                f"Insufficient data for {symbol}: "
                f"required {min_candles}, got {actual_count}"
            )

        return LoadResult(
            df=df,
            load_type=load_type,
            api_calls=api_calls,
            new_candles=new_candles,
        )
