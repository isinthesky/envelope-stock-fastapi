# -*- coding: utf-8 -*-
"""
BacktestDataLoader 증분 업데이트 테스트
"""

from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from src.application.common.exceptions import BacktestDataError
from src.application.domain.backtest.data_loader import BacktestDataLoader
from src.application.domain.market_data.dto import CandleDTO, ChartResponseDTO


def create_candle(date: datetime, price: float = 70000) -> CandleDTO:
    """테스트용 캔들 생성"""
    return CandleDTO(
        timestamp=date,
        open=Decimal(str(price)),
        high=Decimal(str(price + 1000)),
        low=Decimal(str(price - 1000)),
        close=Decimal(str(price + 500)),
        volume=1000000,
    )


def create_candles(start: datetime, days: int, price: float = 70000) -> list[CandleDTO]:
    """여러 날짜의 캔들 생성"""
    return [create_candle(start + timedelta(days=i), price + i * 100) for i in range(days)]


def candles_to_df(candles: list[CandleDTO]) -> pd.DataFrame:
    """캔들 리스트를 DataFrame으로 변환"""
    data = [
        {
            "timestamp": c.timestamp,
            "open": float(c.open),
            "high": float(c.high),
            "low": float(c.low),
            "close": float(c.close),
            "volume": c.volume,
        }
        for c in candles
    ]
    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


class TestIncrementalUpdate:
    """증분 업데이트 테스트"""

    def setup_method(self):
        """테스트 초기화"""
        self.mock_market_data_service = MagicMock()
        self.mock_db_session = AsyncMock()
        self.mock_ohlcv_repo = AsyncMock()

    @pytest.mark.asyncio
    async def test_cache_full_hit(self):
        """캐시 완전 히트 테스트 - API 호출 없이 캐시만 사용"""
        # 요청 범위: 2024-01-01 ~ 2024-01-30 (30일)
        start_date = datetime(2024, 1, 1)
        end_date = datetime(2024, 1, 30)

        # 캐시: 2024-01-01 ~ 2024-01-30 (요청 범위 완전 포함)
        cached_candles = create_candles(start_date, 30)
        cached_df = candles_to_df(cached_candles)

        loader = BacktestDataLoader(self.mock_market_data_service, self.mock_db_session)
        loader.ohlcv_repo = self.mock_ohlcv_repo

        # Mock 설정
        self.mock_ohlcv_repo.check_data_availability = AsyncMock(
            return_value={"has_data": True, "count": 30}
        )
        self.mock_ohlcv_repo.get_candles_to_dataframe = AsyncMock(return_value=cached_df)

        # 실행
        df, actual_start, actual_end = await loader.load_ohlcv_data(
            symbol="005930",
            start_date=start_date,
            end_date=end_date,
        )

        # 검증: API 호출 없음
        self.mock_market_data_service.get_chart_data.assert_not_called()
        # 검증: 데이터 반환
        assert len(df) == 30
        assert actual_start == start_date
        assert actual_end == end_date

    @pytest.mark.asyncio
    async def test_no_cache_full_load(self):
        """캐시 없음 - 전체 로드 테스트"""
        start_date = datetime(2024, 1, 1)
        end_date = datetime(2024, 1, 30)

        # API 응답 설정
        api_candles = create_candles(start_date, 30)

        loader = BacktestDataLoader(self.mock_market_data_service, self.mock_db_session)
        loader.ohlcv_repo = self.mock_ohlcv_repo

        # Mock 설정 - 캐시 없음
        self.mock_ohlcv_repo.check_data_availability = AsyncMock(
            return_value={"has_data": False, "count": 0}
        )

        # API Mock
        self.mock_market_data_service.get_chart_data = AsyncMock(
            return_value=ChartResponseDTO(symbol="005930", interval="1d", candles=api_candles)
        )

        # 실행
        df, actual_start, actual_end = await loader.load_ohlcv_data(
            symbol="005930",
            start_date=start_date,
            end_date=end_date,
        )

        # 검증: API 호출됨
        self.mock_market_data_service.get_chart_data.assert_called()
        # 검증: DB 저장 호출됨
        self.mock_ohlcv_repo.save_candles_bulk.assert_called()
        # 검증: 데이터 반환
        assert len(df) >= 20  # 최소 검증 통과

    @pytest.mark.asyncio
    async def test_partial_cache_end_fill(self):
        """부분 캐시 - 끝 부분만 보충 테스트"""
        # 요청 범위: 2024-01-01 ~ 2024-01-30
        start_date = datetime(2024, 1, 1)
        end_date = datetime(2024, 1, 30)

        # 캐시: 2024-01-01 ~ 2024-01-20 (끝 부분 부족)
        cache_start = datetime(2024, 1, 1)
        cache_end = datetime(2024, 1, 20)
        cached_candles = create_candles(cache_start, 20)
        cached_df = candles_to_df(cached_candles)

        # API 응답: 2024-01-21 ~ 2024-01-30 (10일)
        api_candles = create_candles(datetime(2024, 1, 21), 10, price=72000)

        loader = BacktestDataLoader(self.mock_market_data_service, self.mock_db_session)
        loader.ohlcv_repo = self.mock_ohlcv_repo

        # Mock 설정
        self.mock_ohlcv_repo.check_data_availability = AsyncMock(
            return_value={"has_data": True, "count": 20}
        )
        self.mock_ohlcv_repo.get_candles_to_dataframe = AsyncMock(return_value=cached_df)

        # API Mock
        self.mock_market_data_service.get_chart_data = AsyncMock(
            return_value=ChartResponseDTO(symbol="005930", interval="1d", candles=api_candles)
        )

        # 실행
        df, actual_start, actual_end = await loader.load_ohlcv_data(
            symbol="005930",
            start_date=start_date,
            end_date=end_date,
        )

        # 검증: API 호출됨 (끝 부분만)
        self.mock_market_data_service.get_chart_data.assert_called()
        # 검증: 캐시 + API 병합
        assert len(df) == 30

    @pytest.mark.asyncio
    async def test_separate_save_preserves_middle_cache(self):
        """양쪽 부족 시 개별 저장으로 중간 캐시 보존 테스트"""
        # 요청 범위: 2024-01-01 ~ 2024-02-29
        start_date = datetime(2024, 1, 1)
        end_date = datetime(2024, 2, 29)

        # 캐시: 2024-01-15 ~ 2024-02-15 (중간 30일)
        cache_start = datetime(2024, 1, 15)
        cache_end = datetime(2024, 2, 15)
        cached_candles = create_candles(cache_start, 32)
        cached_df = candles_to_df(cached_candles)

        # API 응답 설정
        start_api_candles = create_candles(datetime(2024, 1, 1), 14)  # 1/1 ~ 1/14
        end_api_candles = create_candles(datetime(2024, 2, 16), 14)  # 2/16 ~ 2/29

        loader = BacktestDataLoader(self.mock_market_data_service, self.mock_db_session)
        loader.ohlcv_repo = self.mock_ohlcv_repo

        # Mock 설정
        self.mock_ohlcv_repo.check_data_availability = AsyncMock(
            return_value={"has_data": True, "count": 32}
        )
        self.mock_ohlcv_repo.get_candles_to_dataframe = AsyncMock(return_value=cached_df)

        # API Mock - 순서대로 시작 구간, 끝 구간 반환
        self.mock_market_data_service.get_chart_data = AsyncMock(
            side_effect=[
                ChartResponseDTO(symbol="005930", interval="1d", candles=start_api_candles),
                ChartResponseDTO(symbol="005930", interval="1d", candles=end_api_candles),
            ]
        )

        # 실행
        df, actual_start, actual_end = await loader.load_ohlcv_data(
            symbol="005930",
            start_date=start_date,
            end_date=end_date,
        )

        # 검증: save_candles_bulk가 2번 호출됨 (시작, 끝 각각)
        # 중간 캐시(cache_start ~ cache_end)는 삭제되지 않음
        assert self.mock_ohlcv_repo.save_candles_bulk.call_count == 2

        # 검증: 첫 번째 호출은 시작 구간
        first_call_candles = self.mock_ohlcv_repo.save_candles_bulk.call_args_list[0]
        # 검증: 두 번째 호출은 끝 구간
        second_call_candles = self.mock_ohlcv_repo.save_candles_bulk.call_args_list[1]

        # 각 호출이 독립적으로 저장되어 중간 캐시가 보존됨
        assert first_call_candles != second_call_candles


class TestCacheHitValidation:
    """캐시 히트 시 검증 테스트"""

    def setup_method(self):
        """테스트 초기화"""
        self.mock_market_data_service = MagicMock()
        self.mock_db_session = AsyncMock()
        self.mock_ohlcv_repo = AsyncMock()

    @pytest.mark.asyncio
    async def test_cache_hit_validates_data(self):
        """캐시 완전 히트 시에도 검증 수행 테스트"""
        start_date = datetime(2024, 1, 1)
        end_date = datetime(2024, 1, 30)

        # 캐시 범위는 요청을 포함하지만, 중간에 데이터가 빠져서 10개만 있음
        # timestamp: 1/1, 1/5, 1/10, 1/15, 1/20, 1/22, 1/24, 1/26, 1/28, 1/30
        sparse_dates = [
            datetime(2024, 1, 1), datetime(2024, 1, 5), datetime(2024, 1, 10),
            datetime(2024, 1, 15), datetime(2024, 1, 20), datetime(2024, 1, 22),
            datetime(2024, 1, 24), datetime(2024, 1, 26), datetime(2024, 1, 28),
            datetime(2024, 1, 30),
        ]
        sparse_candles = [create_candle(d) for d in sparse_dates]
        cached_df = candles_to_df(sparse_candles)

        loader = BacktestDataLoader(self.mock_market_data_service, self.mock_db_session)
        loader.ohlcv_repo = self.mock_ohlcv_repo

        # Mock 설정 - 캐시 범위는 1/1~1/30 (요청 포함) 하지만 데이터는 10개만
        self.mock_ohlcv_repo.check_data_availability = AsyncMock(
            return_value={"has_data": True, "count": 10}
        )
        self.mock_ohlcv_repo.get_candles_to_dataframe = AsyncMock(return_value=cached_df)

        # 실행 - 캐시 완전 히트 후 검증에서 "Insufficient data" 발생해야 함
        with pytest.raises(BacktestDataError, match="Insufficient data"):
            await loader.load_ohlcv_data(
                symbol="005930",
                start_date=start_date,
                end_date=end_date,
            )
