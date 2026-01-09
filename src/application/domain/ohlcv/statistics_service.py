# -*- coding: utf-8 -*-
"""
OHLCV Statistics Service - OHLCV 캐시 통계 및 모니터링

캐시 통계 조회, 건강 상태 진단, API 호출 예상치 계산 등
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.database.repositories.ohlcv_repository import OHLCVRepository
from src.application.domain.ohlcv.dto import (
    ApiCallEstimateDTO,
    CacheHealthDTO,
    CacheStatisticsDTO,
    SymbolCacheInfoDTO,
)

logger = logging.getLogger(__name__)


class OHLCVStatisticsService:
    """
    OHLCV 캐시 통계 및 모니터링 서비스
    """

    def __init__(self, session: AsyncSession) -> None:
        """
        Args:
            session: Database Session
        """
        self.session = session
        self.ohlcv_repo = OHLCVRepository(session)

    async def get_cache_statistics(self) -> CacheStatisticsDTO:
        """
        전체 캐시 통계 조회

        Returns:
            CacheStatisticsDTO: 캐시 통계 정보
        """
        summary = await self.ohlcv_repo.get_cache_summary()

        # 캐시 크기 추정 (캔들당 약 100 bytes)
        cache_size_mb = (summary["total_candles"] * 100) / (1024 * 1024)

        return CacheStatisticsDTO(
            total_symbols=summary["total_symbols"],
            total_candles=summary["total_candles"],
            oldest_data_date=summary["oldest_date"],
            newest_data_date=summary["newest_date"],
            cache_size_mb=round(cache_size_mb, 2),
            symbols_by_interval=summary["symbols_by_interval"],
            intervals=summary["intervals"],
        )

    async def get_symbol_statistics(
        self,
        symbol: str,
        interval: str = "1d",
    ) -> SymbolCacheInfoDTO:
        """
        종목별 캐시 통계 조회

        Args:
            symbol: 종목코드
            interval: 캔들 간격

        Returns:
            SymbolCacheInfoDTO: 종목 캐시 정보
        """
        stats = await self.ohlcv_repo.get_symbol_stats(symbol, interval)

        return SymbolCacheInfoDTO(
            symbol=symbol,
            candle_count=stats["total_candles"],
            earliest_date=stats["earliest_date"],
            latest_date=stats["latest_date"],
            interval=interval,
        )

    async def get_cache_health(
        self,
        freshness_threshold_days: int = 7,
    ) -> CacheHealthDTO:
        """
        캐시 건강 상태 진단

        Args:
            freshness_threshold_days: 신선도 기준 (일)

        Returns:
            CacheHealthDTO: 건강 상태 정보
        """
        recommendations = []

        # 오래된 데이터 보유 종목 조회
        stale_data = await self.ohlcv_repo.get_symbols_with_stale_data(
            freshness_days=freshness_threshold_days,
        )
        stale_symbols = [item["symbol"] for item in stale_data]

        if stale_symbols:
            recommendations.append(
                f"{len(stale_symbols)}개 종목의 데이터가 {freshness_threshold_days}일 이상 오래되었습니다. "
                "워밍업을 실행하세요."
            )

        # 최근 데이터 없는 종목 확인 (3일 이상 오래된 것)
        missing_recent = await self.ohlcv_repo.get_symbols_with_stale_data(
            freshness_days=3,
        )
        missing_recent_symbols = [item["symbol"] for item in missing_recent]

        # stale_symbols에서 이미 포함된 것 제외
        stale_set = set(stale_symbols)
        missing_recent_only = [s for s in missing_recent_symbols if s not in stale_set]

        if missing_recent_only:
            recommendations.append(
                f"{len(missing_recent_only)}개 종목의 최근 3일 데이터가 없습니다."
            )

        # 전체 캐시 통계
        summary = await self.ohlcv_repo.get_cache_summary()

        if summary["total_candles"] == 0:
            recommendations.append("캐시가 비어있습니다. 초기 워밍업이 필요합니다.")

        # 건강 상태 판정
        is_healthy = len(stale_symbols) == 0 and len(missing_recent_only) == 0

        return CacheHealthDTO(
            is_healthy=is_healthy,
            stale_symbols=stale_symbols[:20],  # 최대 20개
            stale_count=len(stale_symbols),
            missing_recent_data=missing_recent_only[:20],
            gap_detected=[],  # 상세 분석은 별도 API로 제공
            recommendations=recommendations,
            checked_at=datetime.now(),
        )

    async def get_api_call_estimate(
        self,
        symbols: list[str],
        days: int = 240,
        interval: str = "1d",
    ) -> ApiCallEstimateDTO:
        """
        API 호출 예상치 계산

        Args:
            symbols: 대상 종목 목록
            days: 조회 기간 (일)
            interval: 캔들 간격

        Returns:
            ApiCallEstimateDTO: API 호출 예상치
        """
        if not symbols:
            return ApiCallEstimateDTO(
                total_symbols=0,
                cached_symbols=0,
                api_calls_needed=0,
                estimated_time_seconds=0,
                estimated_time_formatted="0초",
            )

        # 캐시된 종목 확인
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        cached_count = 0
        api_calls_needed = 0

        # API 호출 패턴: 120일씩 2회 호출
        calls_per_symbol = 2

        for symbol in symbols:
            availability = await self.ohlcv_repo.check_data_availability(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                interval=interval,
            )

            if availability["is_complete"]:
                cached_count += 1
            else:
                api_calls_needed += calls_per_symbol

        # 예상 시간 계산 (API 호출당 약 0.5초 + 레이트 리밋 여유)
        avg_time_per_call = 0.6  # 초
        estimated_seconds = api_calls_needed * avg_time_per_call

        # 시간 포맷팅
        if estimated_seconds < 60:
            time_formatted = f"{int(estimated_seconds)}초"
        elif estimated_seconds < 3600:
            minutes = int(estimated_seconds / 60)
            seconds = int(estimated_seconds % 60)
            time_formatted = f"{minutes}분 {seconds}초"
        else:
            hours = int(estimated_seconds / 3600)
            minutes = int((estimated_seconds % 3600) / 60)
            time_formatted = f"{hours}시간 {minutes}분"

        return ApiCallEstimateDTO(
            total_symbols=len(symbols),
            cached_symbols=cached_count,
            api_calls_needed=api_calls_needed,
            estimated_time_seconds=round(estimated_seconds, 1),
            estimated_time_formatted=time_formatted,
        )

    async def get_symbols_needing_update(
        self,
        freshness_days: int = 3,
        interval: str = "1d",
    ) -> list[str]:
        """
        업데이트가 필요한 종목 목록 조회

        Args:
            freshness_days: 신선도 기준 (일)
            interval: 캔들 간격

        Returns:
            list[str]: 업데이트 필요 종목 목록
        """
        stale_data = await self.ohlcv_repo.get_symbols_with_stale_data(
            freshness_days=freshness_days,
            interval=interval,
        )
        return [item["symbol"] for item in stale_data]

    async def get_data_freshness_summary(
        self,
        interval: str = "1d",
    ) -> dict:
        """
        데이터 신선도 요약

        Args:
            interval: 캔들 간격

        Returns:
            dict: 신선도 요약 정보
        """
        latest_dates = await self.ohlcv_repo.get_symbols_latest_dates(interval)

        if not latest_dates:
            return {
                "total_symbols": 0,
                "fresh_count": 0,
                "stale_count": 0,
                "very_stale_count": 0,
                "oldest_symbol": None,
                "newest_symbol": None,
            }

        now = datetime.now()
        fresh_threshold = now - timedelta(days=3)
        stale_threshold = now - timedelta(days=7)

        fresh_count = 0
        stale_count = 0
        very_stale_count = 0

        oldest_symbol = None
        oldest_date = None
        newest_symbol = None
        newest_date = None

        for symbol, latest_date in latest_dates.items():
            # 타임존 정규화
            if latest_date.tzinfo is not None:
                latest_date = latest_date.replace(tzinfo=None)

            if latest_date >= fresh_threshold:
                fresh_count += 1
            elif latest_date >= stale_threshold:
                stale_count += 1
            else:
                very_stale_count += 1

            if oldest_date is None or latest_date < oldest_date:
                oldest_date = latest_date
                oldest_symbol = symbol

            if newest_date is None or latest_date > newest_date:
                newest_date = latest_date
                newest_symbol = symbol

        return {
            "total_symbols": len(latest_dates),
            "fresh_count": fresh_count,  # 3일 이내
            "stale_count": stale_count,  # 3~7일
            "very_stale_count": very_stale_count,  # 7일 이상
            "oldest_symbol": oldest_symbol,
            "oldest_date": oldest_date,
            "newest_symbol": newest_symbol,
            "newest_date": newest_date,
        }
