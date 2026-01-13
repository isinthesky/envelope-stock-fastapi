# -*- coding: utf-8 -*-
"""
OHLCV Data Loader 단위 테스트

타임존 정규화, chunking, 통계 추적, 증분 업데이트 경로 검증
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

# 순환 import 방지를 위해 lazy import
from src.application.domain.strategy.ohlcv_data_loader import (
    MAX_API_DAYS_PER_CALL,
    LoadResult,
    LoadType,
    OHLCVDataLoader,
    normalize_df_timestamps,
    normalize_timestamp,
)


class TestTimezoneNormalization:
    """타임존 정규화 테스트"""

    def test_normalize_naive_timestamp(self):
        """tz-naive datetime을 UTC로 정규화"""
        naive_dt = datetime(2024, 1, 15, 9, 0, 0)
        result = normalize_timestamp(naive_dt)

        assert result.tzinfo is not None
        assert result.tzinfo == timezone.utc
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15

    def test_normalize_aware_timestamp_utc(self):
        """UTC tz-aware datetime 유지"""
        aware_dt = datetime(2024, 1, 15, 9, 0, 0, tzinfo=timezone.utc)
        result = normalize_timestamp(aware_dt)

        assert result.tzinfo == timezone.utc
        assert result == aware_dt

    def test_normalize_aware_timestamp_kst(self):
        """KST tz-aware datetime을 UTC로 변환"""
        kst = timezone(timedelta(hours=9))
        kst_dt = datetime(2024, 1, 15, 18, 0, 0, tzinfo=kst)  # 18:00 KST
        result = normalize_timestamp(kst_dt)

        assert result.tzinfo == timezone.utc
        assert result.hour == 9  # 18:00 KST = 09:00 UTC

    def test_normalize_df_timestamps_naive(self):
        """tz-naive DataFrame을 UTC로 정규화"""
        df = pd.DataFrame({
            "timestamp": pd.to_datetime(["2024-01-15", "2024-01-16", "2024-01-17"]),
            "close": [100.0, 101.0, 102.0],
        })

        result = normalize_df_timestamps(df)

        assert result["timestamp"].dt.tz is not None
        assert str(result["timestamp"].dt.tz) == "UTC"

    def test_normalize_df_timestamps_aware(self):
        """tz-aware DataFrame을 UTC로 변환"""
        kst = timezone(timedelta(hours=9))
        df = pd.DataFrame({
            "timestamp": pd.to_datetime(["2024-01-15", "2024-01-16"]).tz_localize("Asia/Seoul"),
            "close": [100.0, 101.0],
        })

        result = normalize_df_timestamps(df)

        assert str(result["timestamp"].dt.tz) == "UTC"

    def test_normalize_df_timestamps_empty(self):
        """빈 DataFrame 처리"""
        df = pd.DataFrame(columns=["timestamp", "close"])
        result = normalize_df_timestamps(df)
        assert result.empty

    def test_normalize_df_timestamps_no_timestamp_column(self):
        """timestamp 컬럼이 없는 DataFrame 처리"""
        df = pd.DataFrame({"close": [100.0, 101.0]})
        result = normalize_df_timestamps(df)
        assert "timestamp" not in result.columns


class TestMergeTimezones:
    """타임존 혼합 병합 테스트"""

    def test_merge_naive_and_aware_after_normalization(self):
        """정규화 후 naive와 aware DataFrame 병합"""
        # 캐시 데이터 (tz-aware)
        cached_df = pd.DataFrame({
            "timestamp": pd.to_datetime(["2024-01-15", "2024-01-16"]).tz_localize("UTC"),
            "close": [100.0, 101.0],
        })

        # API 데이터 (tz-naive)
        api_df = pd.DataFrame({
            "timestamp": pd.to_datetime(["2024-01-17", "2024-01-18"]),
            "close": [102.0, 103.0],
        })

        # 정규화
        cached_df = normalize_df_timestamps(cached_df)
        api_df = normalize_df_timestamps(api_df)

        # 병합 - TypeError 없이 성공해야 함
        merged = pd.concat([cached_df, api_df], ignore_index=True)
        merged = merged.sort_values("timestamp").reset_index(drop=True)

        assert len(merged) == 4
        assert merged["timestamp"].dt.tz is not None

    def test_merge_with_duplicates(self):
        """중복 타임스탬프 제거"""
        df1 = pd.DataFrame({
            "timestamp": pd.to_datetime(["2024-01-15", "2024-01-16"]).tz_localize("UTC"),
            "close": [100.0, 101.0],
        })
        df2 = pd.DataFrame({
            "timestamp": pd.to_datetime(["2024-01-16", "2024-01-17"]).tz_localize("UTC"),
            "close": [101.5, 102.0],  # 16일 중복
        })

        merged = pd.concat([df1, df2], ignore_index=True)
        merged = merged.drop_duplicates(subset=["timestamp"]).sort_values("timestamp")

        assert len(merged) == 3  # 중복 제거 후 3개


class TestChunkingConstants:
    """Chunking 상수 테스트"""

    def test_max_api_days_per_call(self):
        """API 호출당 최대 일수 확인"""
        assert MAX_API_DAYS_PER_CALL == 100

    def test_chunk_calculation(self):
        """장기간 데이터의 chunk 분할 계산"""
        stale_days = 250  # 250일 동안 캐시 업데이트 안함
        expected_chunks = (stale_days // MAX_API_DAYS_PER_CALL) + 1

        # 250일 / 100일 = 2.5 → 3개의 chunk 필요
        assert expected_chunks == 3


class TestDateRangeCalculation:
    """날짜 범위 계산 테스트"""

    def test_incremental_update_range(self):
        """증분 업데이트 날짜 범위 계산"""
        last_cached = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end_date = datetime(2024, 4, 15, tzinfo=timezone.utc)  # 105일 후

        fetch_start = last_cached + timedelta(days=1)
        days_gap = (end_date - last_cached).days

        assert days_gap == 105
        assert fetch_start.day == 2  # 1월 2일부터 시작

        # 첫 번째 chunk: 1월 2일 ~ 4월 11일 (100일)
        chunk1_end = min(fetch_start + timedelta(days=MAX_API_DAYS_PER_CALL), end_date)
        assert (chunk1_end - fetch_start).days == MAX_API_DAYS_PER_CALL

        # 두 번째 chunk: 4월 12일 ~ 4월 15일 (4일)
        chunk2_start = chunk1_end + timedelta(days=1)
        assert chunk2_start < end_date


# ==================== 증분 업데이트 경로 테스트 ====================


def create_mock_candle(date: datetime, close: float = 100.0) -> MagicMock:
    """테스트용 캔들 생성 (CandleDTO mock)"""
    candle = MagicMock()
    candle.timestamp = date
    candle.open = Decimal(str(close - 1))
    candle.high = Decimal(str(close + 1))
    candle.low = Decimal(str(close - 2))
    candle.close = Decimal(str(close))
    candle.volume = 1000000
    return candle


def create_cached_df(dates: list[datetime]) -> pd.DataFrame:
    """테스트용 캐시 DataFrame 생성"""
    df = pd.DataFrame({
        "timestamp": pd.to_datetime(dates).tz_localize("UTC"),
        "open": [99.0] * len(dates),
        "high": [101.0] * len(dates),
        "low": [98.0] * len(dates),
        "close": [100.0] * len(dates),
        "volume": [1000000] * len(dates),
    })
    return df


class TestIncrementalUpdatePaths:
    """증분 업데이트 경로 테스트"""

    @pytest.fixture
    def loader(self):
        """세션 없는 로더 (API only)"""
        return OHLCVDataLoader(session=None)

    @pytest.mark.asyncio
    async def test_incremental_update_success_short_gap(self, loader):
        """짧은 기간 (< 100일) 증분 업데이트 성공"""
        # Given: 7일 전 캐시
        last_cached = datetime(2024, 1, 8, tzinfo=timezone.utc)
        end_date = datetime(2024, 1, 15, tzinfo=timezone.utc)
        cached_df = create_cached_df([
            datetime(2024, 1, 1),
            datetime(2024, 1, 2),
            datetime(2024, 1, 3),
        ])

        # Mock API response
        new_candles = [
            create_mock_candle(datetime(2024, 1, 9), 101.0),
            create_mock_candle(datetime(2024, 1, 10), 102.0),
        ]

        mock_chart_response = MagicMock()
        mock_chart_response.candles = new_candles

        with patch.object(loader, "_get_market_data_service") as mock_service:
            mock_mds = AsyncMock()
            mock_mds.get_chart_data = AsyncMock(return_value=mock_chart_response)
            mock_service.return_value = mock_mds

            # When
            result_df, new_count, api_calls = await loader._incremental_update(
                symbol="005930",
                cached_df=cached_df,
                last_cached_date=last_cached,
                end_date=end_date,
                interval="1d",
            )

            # Then
            assert result_df is not None
            assert new_count == 2
            assert api_calls == 1  # 짧은 기간이므로 1회 호출
            assert len(result_df) == 5  # 3 cached + 2 new

    @pytest.mark.asyncio
    async def test_incremental_update_success_long_gap_chunking(self, loader):
        """긴 기간 (> 100일) 증분 업데이트 - chunking 동작"""
        # Given: 150일 전 캐시
        last_cached = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end_date = datetime(2024, 6, 1, tzinfo=timezone.utc)  # ~150일 후
        cached_df = create_cached_df([datetime(2024, 1, 1)])

        # Mock API responses (각 chunk마다 호출)
        chunk1_candles = [create_mock_candle(datetime(2024, 2, 1), 101.0)]
        chunk2_candles = [create_mock_candle(datetime(2024, 5, 1), 102.0)]

        mock_responses = [
            MagicMock(candles=chunk1_candles),
            MagicMock(candles=chunk2_candles),
        ]

        with patch.object(loader, "_get_market_data_service") as mock_service:
            mock_mds = AsyncMock()
            mock_mds.get_chart_data = AsyncMock(side_effect=mock_responses)
            mock_service.return_value = mock_mds

            # When
            result_df, new_count, api_calls = await loader._incremental_update(
                symbol="005930",
                cached_df=cached_df,
                last_cached_date=last_cached,
                end_date=end_date,
                interval="1d",
            )

            # Then
            assert result_df is not None
            assert api_calls == 2  # 150일 / 100일 = 2 chunks

    @pytest.mark.asyncio
    async def test_incremental_update_no_new_data(self, loader):
        """신규 데이터 없음 (주말/휴일)"""
        # Given: 2일 전 캐시 (토요일)
        last_cached = datetime(2024, 1, 13, tzinfo=timezone.utc)  # 토요일
        end_date = datetime(2024, 1, 15, tzinfo=timezone.utc)  # 월요일
        cached_df = create_cached_df([datetime(2024, 1, 12), datetime(2024, 1, 13)])

        mock_chart_response = MagicMock()
        mock_chart_response.candles = []  # 주말이라 데이터 없음

        with patch.object(loader, "_get_market_data_service") as mock_service:
            mock_mds = AsyncMock()
            mock_mds.get_chart_data = AsyncMock(return_value=mock_chart_response)
            mock_service.return_value = mock_mds

            # When
            result_df, new_count, api_calls = await loader._incremental_update(
                symbol="005930",
                cached_df=cached_df,
                last_cached_date=last_cached,
                end_date=end_date,
                interval="1d",
            )

            # Then
            assert result_df is not None
            assert new_count == 0
            assert api_calls == 1
            assert len(result_df) == 2  # 캐시 그대로

    @pytest.mark.asyncio
    async def test_incremental_update_already_fresh(self, loader):
        """이미 최신 (gap <= 1일)"""
        # Given: 어제 캐시
        last_cached = datetime(2024, 1, 14, tzinfo=timezone.utc)
        end_date = datetime(2024, 1, 15, tzinfo=timezone.utc)
        cached_df = create_cached_df([datetime(2024, 1, 14)])

        # When: API 호출 없이 반환
        result_df, new_count, api_calls = await loader._incremental_update(
            symbol="005930",
            cached_df=cached_df,
            last_cached_date=last_cached,
            end_date=end_date,
            interval="1d",
        )

        # Then
        assert result_df is not None
        assert new_count == 0
        assert api_calls == 0  # API 호출 없음

    @pytest.mark.asyncio
    async def test_incremental_update_api_failure(self, loader):
        """API 호출 실패 - fallback 처리"""
        # Given
        last_cached = datetime(2024, 1, 8, tzinfo=timezone.utc)
        end_date = datetime(2024, 1, 15, tzinfo=timezone.utc)
        cached_df = create_cached_df([datetime(2024, 1, 8)])

        with patch.object(loader, "_get_market_data_service") as mock_service:
            mock_mds = AsyncMock()
            mock_mds.get_chart_data = AsyncMock(side_effect=Exception("API Error"))
            mock_service.return_value = mock_mds

            # When
            result_df, new_count, api_calls = await loader._incremental_update(
                symbol="005930",
                cached_df=cached_df,
                last_cached_date=last_cached,
                end_date=end_date,
                interval="1d",
            )

            # Then: 실패 시 None 반환 → 호출자가 full load로 fallback
            assert result_df is None
            assert new_count == 0
            # api_calls는 예외 발생 전 시점의 값 (try 블록 진입 전 0)

    @pytest.mark.asyncio
    async def test_incremental_update_duplicate_removal(self, loader):
        """중복 캔들 제거"""
        # Given
        last_cached = datetime(2024, 1, 8, tzinfo=timezone.utc)
        end_date = datetime(2024, 1, 15, tzinfo=timezone.utc)
        cached_df = create_cached_df([datetime(2024, 1, 8)])

        # API가 중복 캔들 반환
        duplicate_candles = [
            create_mock_candle(datetime(2024, 1, 9), 101.0),
            create_mock_candle(datetime(2024, 1, 9), 101.5),  # 동일 날짜
            create_mock_candle(datetime(2024, 1, 10), 102.0),
        ]

        mock_chart_response = MagicMock()
        mock_chart_response.candles = duplicate_candles

        with patch.object(loader, "_get_market_data_service") as mock_service:
            mock_mds = AsyncMock()
            mock_mds.get_chart_data = AsyncMock(return_value=mock_chart_response)
            mock_service.return_value = mock_mds

            # When
            result_df, new_count, api_calls = await loader._incremental_update(
                symbol="005930",
                cached_df=cached_df,
                last_cached_date=last_cached,
                end_date=end_date,
                interval="1d",
            )

            # Then: 중복 제거 후 2개 (1/9, 1/10)
            assert result_df is not None
            assert new_count == 2  # 중복 제거 후 카운트
            # 병합 후 총 3개 (1/8 cached + 1/9 + 1/10)
            assert len(result_df) == 3


class TestLoadResult:
    """LoadResult 데이터 클래스 테스트"""

    def test_load_result_cache_hit(self):
        """캐시 히트 결과"""
        df = create_cached_df([datetime(2024, 1, 1)])
        result = LoadResult(
            df=df,
            load_type=LoadType.CACHE_HIT,
            api_calls=0,
            new_candles=0,
        )

        assert result.load_type == LoadType.CACHE_HIT
        assert result.api_calls == 0
        assert result.new_candles == 0

    def test_load_result_incremental(self):
        """증분 업데이트 결과"""
        df = create_cached_df([datetime(2024, 1, 1)])
        result = LoadResult(
            df=df,
            load_type=LoadType.INCREMENTAL,
            api_calls=2,
            new_candles=15,
        )

        assert result.load_type == LoadType.INCREMENTAL
        assert result.api_calls == 2
        assert result.new_candles == 15

    def test_load_result_full_load(self):
        """전체 로딩 결과"""
        df = create_cached_df([datetime(2024, 1, 1)])
        result = LoadResult(
            df=df,
            load_type=LoadType.FULL_LOAD,
            api_calls=2,
            new_candles=0,
        )

        assert result.load_type == LoadType.FULL_LOAD
        assert result.api_calls == 2


class TestLoadType:
    """LoadType Enum 테스트"""

    def test_load_type_values(self):
        """LoadType 값 확인"""
        assert LoadType.CACHE_HIT.value == "cache_hit"
        assert LoadType.INCREMENTAL.value == "incremental"
        assert LoadType.FULL_LOAD.value == "full_load"

    def test_load_type_string_comparison(self):
        """문자열 비교 가능 (str Enum)"""
        # str Enum이므로 직접 비교 가능
        assert LoadType.CACHE_HIT == "cache_hit"
        assert LoadType.INCREMENTAL == "incremental"
        # .value로도 접근 가능
        assert LoadType.FULL_LOAD.value == "full_load"
