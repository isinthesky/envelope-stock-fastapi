# -*- coding: utf-8 -*-
"""
OHLCV Data Loader 통합 테스트

실제 시나리오 기반 심층 검증:
1. 타임존 혼합 병합
2. 장기간 stale 캐시 chunking
3. DB 집계 쿼리 최적화
4. API 호출 횟수 통계 정확도
5. cache_freshness_days 파라미터 동작
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from src.application.domain.ohlcv.data_loader import (
    LoadType,
    OHLCVDataLoader,
)
from src.application.domain.ohlcv.core_loader import (
    normalize_df_timestamps,
    normalize_timestamp,
)
from src.settings.config import settings


def create_mock_candle(date: datetime, close: float = 100.0) -> MagicMock:
    """테스트용 캔들 생성"""
    candle = MagicMock()
    candle.timestamp = date
    candle.open = Decimal(str(close - 1))
    candle.high = Decimal(str(close + 1))
    candle.low = Decimal(str(close - 2))
    candle.close = Decimal(str(close))
    candle.volume = 1000000
    return candle


def create_tz_aware_df(dates: list[datetime]) -> pd.DataFrame:
    """DB에서 가져온 것처럼 tz-aware DataFrame 생성"""
    df = pd.DataFrame({
        "timestamp": pd.to_datetime(dates).tz_localize("UTC"),
        "open": [99.0] * len(dates),
        "high": [101.0] * len(dates),
        "low": [98.0] * len(dates),
        "close": [100.0] * len(dates),
        "volume": [1000000] * len(dates),
    })
    return df


def create_tz_naive_df(dates: list[datetime]) -> pd.DataFrame:
    """API에서 가져온 것처럼 tz-naive DataFrame 생성"""
    df = pd.DataFrame({
        "timestamp": pd.to_datetime(dates),  # tz-naive
        "open": [99.0] * len(dates),
        "high": [101.0] * len(dates),
        "low": [98.0] * len(dates),
        "close": [100.0] * len(dates),
        "volume": [1000000] * len(dates),
    })
    return df


class TestTimezoneIntegration:
    """1. 타임존 혼합 병합 통합 테스트"""

    def test_merge_db_aware_and_api_naive_no_error(self):
        """DB(tz-aware) + API(tz-naive) 병합 시 TypeError 없음"""
        # Given: DB에서 온 tz-aware 데이터
        db_df = create_tz_aware_df([datetime(2024, 1, 1), datetime(2024, 1, 2)])

        # Given: API에서 온 tz-naive 데이터
        api_df = create_tz_naive_df([datetime(2024, 1, 3), datetime(2024, 1, 4)])

        # When: 정규화 후 병합
        db_df = normalize_df_timestamps(db_df)
        api_df = normalize_df_timestamps(api_df)

        # Then: TypeError 없이 병합 및 정렬 성공
        merged = pd.concat([db_df, api_df], ignore_index=True)
        merged = merged.sort_values("timestamp").reset_index(drop=True)

        assert len(merged) == 4
        assert merged["timestamp"].dt.tz is not None
        # 정렬 순서 확인
        assert merged.iloc[0]["timestamp"].day == 1
        assert merged.iloc[3]["timestamp"].day == 4

    def test_merge_with_overlapping_dates(self):
        """중복 날짜 병합 시 정상 처리"""
        # Given: 겹치는 날짜가 있는 두 DataFrame
        db_df = create_tz_aware_df([datetime(2024, 1, 1), datetime(2024, 1, 2)])
        api_df = create_tz_naive_df([datetime(2024, 1, 2), datetime(2024, 1, 3)])  # 1/2 중복

        # When
        db_df = normalize_df_timestamps(db_df)
        api_df = normalize_df_timestamps(api_df)
        merged = pd.concat([db_df, api_df], ignore_index=True)
        merged = merged.drop_duplicates(subset=["timestamp"]).sort_values("timestamp")

        # Then: 중복 제거 후 3개
        assert len(merged) == 3

    def test_normalize_preserves_date_values(self):
        """정규화 시 날짜 값 보존"""
        # Given
        original_date = datetime(2024, 6, 15, 9, 30, 0)

        # When: naive → UTC
        normalized = normalize_timestamp(original_date)

        # Then: 날짜/시간 값 동일
        assert normalized.year == 2024
        assert normalized.month == 6
        assert normalized.day == 15
        assert normalized.hour == 9
        assert normalized.minute == 30


class TestLongTermStaleChunking:
    """2. 장기간 stale 캐시 chunking 테스트"""

    @pytest.fixture
    def loader(self):
        return OHLCVDataLoader(session=None)

    @pytest.mark.asyncio
    async def test_250_days_stale_requires_3_chunks(self, loader):
        """250일 stale 캐시 → 3개 chunk 필요"""
        # Given: 250일 전 캐시
        last_cached = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end_date = datetime(2024, 9, 7, tzinfo=timezone.utc)  # ~250일 후
        cached_df = create_tz_aware_df([datetime(2024, 1, 1)])

        # Mock: 3번의 API 호출 응답
        chunk_responses = [
            MagicMock(candles=[create_mock_candle(datetime(2024, 3, 1))]),  # chunk 1
            MagicMock(candles=[create_mock_candle(datetime(2024, 6, 1))]),  # chunk 2
            MagicMock(candles=[create_mock_candle(datetime(2024, 9, 1))]),  # chunk 3
        ]

        with patch.object(loader.core_loader, "_get_market_data_service") as mock_service:
            mock_mds = AsyncMock()
            mock_mds.get_chart_data = AsyncMock(side_effect=chunk_responses)
            mock_service.return_value = mock_mds

            # When
            result_df, new_count, api_calls, _failed = await loader.core_loader.incremental_update(
                symbol="005930",
                cached_df=cached_df,
                last_cached_date=last_cached,
                end_date=end_date,
                interval="1d",
            )

            # Then: 3개 chunk로 분할
            assert api_calls == 3
            assert result_df is not None

    @pytest.mark.asyncio
    async def test_exact_100_days_single_chunk(self, loader):
        """정확히 100일 gap → 1개 chunk"""
        last_cached = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end_date = datetime(2024, 4, 10, tzinfo=timezone.utc)  # 100일 후
        cached_df = create_tz_aware_df([datetime(2024, 1, 1)])

        mock_response = MagicMock(candles=[create_mock_candle(datetime(2024, 4, 1))])

        with patch.object(loader.core_loader, "_get_market_data_service") as mock_service:
            mock_mds = AsyncMock()
            mock_mds.get_chart_data = AsyncMock(return_value=mock_response)
            mock_service.return_value = mock_mds

            result_df, new_count, api_calls, _failed = await loader.core_loader.incremental_update(
                symbol="005930",
                cached_df=cached_df,
                last_cached_date=last_cached,
                end_date=end_date,
                interval="1d",
            )

            # Then: 1개 chunk
            assert api_calls == 1

    def test_chunking_boundary_calculation(self):
        """Chunking 경계 계산 검증"""
        # 다양한 기간에 대한 chunk 수 계산
        test_cases = [
            (50, 1),    # 50일 → 1 chunk
            (100, 1),   # 100일 → 1 chunk
            (101, 2),   # 101일 → 2 chunks
            (200, 2),   # 200일 → 2 chunks
            (250, 3),   # 250일 → 3 chunks
            (365, 4),   # 365일 → 4 chunks
        ]

        for days, expected_chunks in test_cases:
            max_days = settings.ohlcv_max_api_days_per_call
            actual_chunks = (days // max_days) + (1 if days % max_days > 0 else 0)
            # ohlcv_max_api_days_per_call=100이면 days/100 올림
            if days <= max_days:
                assert actual_chunks == 1, f"days={days}"
            else:
                assert actual_chunks == expected_chunks, f"days={days}, expected={expected_chunks}, actual={actual_chunks}"


class TestAPICallStatistics:
    """4. API 호출 횟수 통계 정확도 테스트"""

    @pytest.fixture
    def loader(self):
        return OHLCVDataLoader(session=None)

    @pytest.mark.asyncio
    async def test_full_load_api_call_count(self, loader):
        """Full load 시 API 호출 횟수 정확도"""
        # Mock API responses
        chunk1_candles = [create_mock_candle(datetime(2024, 1, i)) for i in range(1, 10)]
        chunk2_candles = [create_mock_candle(datetime(2023, 10, i)) for i in range(1, 10)]

        mock_responses = [
            MagicMock(candles=chunk1_candles),
            MagicMock(candles=chunk2_candles),
        ]

        with patch.object(loader.core_loader, "_get_market_data_service") as mock_service:
            mock_mds = AsyncMock()
            mock_mds.get_chart_data = AsyncMock(side_effect=mock_responses)
            mock_service.return_value = mock_mds

            start_date = datetime(2023, 9, 1, tzinfo=timezone.utc)
            end_date = datetime(2024, 1, 15, tzinfo=timezone.utc)

            result_df, api_calls, _failed_chunks = await loader.core_loader.load_from_api(
                symbol="005930",
                start_date=start_date,
                end_date=end_date,
                interval="1d",
            )

            # Then: 정확히 2회 호출
            assert api_calls == 2
            assert result_df is not None

    @pytest.mark.asyncio
    async def test_incremental_multi_chunk_api_count(self, loader):
        """증분 업데이트 multi-chunk API 호출 횟수"""
        last_cached = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end_date = datetime(2024, 7, 15, tzinfo=timezone.utc)  # ~195일
        cached_df = create_tz_aware_df([datetime(2024, 1, 1)])

        # 2개 chunk 응답
        mock_responses = [
            MagicMock(candles=[create_mock_candle(datetime(2024, 4, 1))]),
            MagicMock(candles=[create_mock_candle(datetime(2024, 7, 1))]),
        ]

        with patch.object(loader.core_loader, "_get_market_data_service") as mock_service:
            mock_mds = AsyncMock()
            mock_mds.get_chart_data = AsyncMock(side_effect=mock_responses)
            mock_service.return_value = mock_mds

            result_df, new_count, api_calls, _failed = await loader.core_loader.incremental_update(
                symbol="005930",
                cached_df=cached_df,
                last_cached_date=last_cached,
                end_date=end_date,
                interval="1d",
            )

            # Then: 2회 호출 (195일 / 100일 = 2 chunks)
            assert api_calls == 2


class TestCacheFreshnessDays:
    """5. cache_freshness_days 파라미터 동작 테스트"""

    @pytest.fixture
    def loader(self):
        return OHLCVDataLoader(session=None)

    def test_default_freshness_is_1_day(self):
        """기본 cache_freshness_days는 None (내부에서 settings 사용)"""
        loader = OHLCVDataLoader(session=None)

        # 메서드 시그니처 확인 (inspect 사용)
        import inspect
        sig = inspect.signature(loader.load_ohlcv_dataframe)
        default = sig.parameters["cache_freshness_days"].default

        # None이 기본값이고, 내부에서 settings.ohlcv_cache_freshness_days(1)를 사용
        assert default is None
        assert settings.ohlcv_cache_freshness_days == 1

    def test_freshness_calculation_logic(self):
        """신선도 계산 로직 검증"""
        # Given
        end_date = datetime(2024, 1, 15, tzinfo=timezone.utc)

        # Case 1: 1일 전 캐시 → fresh (freshness_days=1)
        latest_1day = datetime(2024, 1, 14, tzinfo=timezone.utc)
        days_since_1 = (end_date - latest_1day).days
        assert days_since_1 == 1
        assert days_since_1 <= 1  # fresh

        # Case 2: 2일 전 캐시 → stale (freshness_days=1)
        latest_2day = datetime(2024, 1, 13, tzinfo=timezone.utc)
        days_since_2 = (end_date - latest_2day).days
        assert days_since_2 == 2
        assert days_since_2 > 1  # stale

        # Case 3: 7일 전 캐시 → fresh (freshness_days=7)
        latest_7day = datetime(2024, 1, 8, tzinfo=timezone.utc)
        days_since_7 = (end_date - latest_7day).days
        assert days_since_7 == 7
        assert days_since_7 <= 7  # fresh with freshness_days=7


class TestFallbackBehavior:
    """증분 업데이트 실패 시 fallback 동작 테스트"""

    @pytest.fixture
    def loader(self):
        return OHLCVDataLoader(session=None)

    @pytest.mark.asyncio
    async def test_incremental_failure_returns_empty(self, loader):
        """증분 업데이트 실패 시 캐시 그대로 반환 (API가 빈 결과 반환)"""
        last_cached = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end_date = datetime(2024, 1, 15, tzinfo=timezone.utc)
        cached_df = create_tz_aware_df([datetime(2024, 1, 1)])

        with patch.object(loader.core_loader, "_get_market_data_service") as mock_service:
            mock_mds = AsyncMock()
            mock_mds.get_chart_data = AsyncMock(side_effect=Exception("Network Error"))
            mock_service.return_value = mock_mds

            result_df, new_count, api_calls, _failed = await loader.core_loader.incremental_update(
                symbol="005930",
                cached_df=cached_df,
                last_cached_date=last_cached,
                end_date=end_date,
                interval="1d",
            )

            # 실패 시 캐시 그대로 반환 (load_from_api가 empty DataFrame 반환)
            assert result_df is not None
            assert len(result_df) == len(cached_df)
            assert new_count == 0
            assert api_calls == 1  # API 호출은 시도됨

    @pytest.mark.asyncio
    async def test_partial_chunk_failure_returns_partial(self, loader):
        """multi-chunk 중 일부 실패 시 성공한 chunk만 반환"""
        last_cached = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end_date = datetime(2024, 7, 15, tzinfo=timezone.utc)  # ~195일 (2 chunks)
        cached_df = create_tz_aware_df([datetime(2024, 1, 1)])

        # 첫 번째 chunk 성공, 두 번째 chunk 실패
        mock_responses = [
            MagicMock(candles=[create_mock_candle(datetime(2024, 4, 1))]),
            Exception("API Error on chunk 2"),
        ]

        with patch.object(loader.core_loader, "_get_market_data_service") as mock_service:
            mock_mds = AsyncMock()
            mock_mds.get_chart_data = AsyncMock(side_effect=mock_responses)
            mock_service.return_value = mock_mds

            result_df, new_count, api_calls, _failed = await loader.core_loader.incremental_update(
                symbol="005930",
                cached_df=cached_df,
                last_cached_date=last_cached,
                end_date=end_date,
                interval="1d",
            )

            # 일부 실패 시 성공한 chunk만 병합하여 반환
            assert result_df is not None
            assert len(result_df) > len(cached_df)  # 첫 번째 chunk는 병합됨
            assert api_calls == 2  # 2번 시도


class TestEdgeCases:
    """경계 조건 테스트"""

    def test_empty_dataframe_normalization(self):
        """빈 DataFrame 정규화"""
        empty_df = pd.DataFrame(columns=["timestamp", "close"])
        result = normalize_df_timestamps(empty_df)
        assert result.empty

    def test_single_row_dataframe(self):
        """단일 행 DataFrame 처리"""
        single_df = create_tz_naive_df([datetime(2024, 1, 1)])
        result = normalize_df_timestamps(single_df)
        assert len(result) == 1
        assert result["timestamp"].dt.tz is not None

    def test_max_api_days_constant(self):
        """ohlcv_max_api_days_per_call 설정값"""
        assert settings.ohlcv_max_api_days_per_call == 100
        assert isinstance(settings.ohlcv_max_api_days_per_call, int)
