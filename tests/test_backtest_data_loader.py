# -*- coding: utf-8 -*-
"""
BacktestDataLoader 테스트
"""

from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from src.application.common.exceptions import BacktestDataError
from src.application.domain.backtest.data_loader import BacktestDataLoader
from src.application.domain.market_data.dto import CandleDTO


class TestBacktestDataLoader:
    """백테스트 데이터 로더 테스트"""

    def setup_method(self):
        """테스트 초기화"""
        # MarketDataService Mock
        self.mock_market_data_service = MagicMock()
        self.loader = BacktestDataLoader(self.mock_market_data_service)

    def test_candles_to_dataframe(self):
        """CandleDTO를 DataFrame으로 변환 테스트"""
        candles = [
            CandleDTO(
                timestamp=datetime(2024, 1, 1),
                open=Decimal("70000"),
                high=Decimal("71000"),
                low=Decimal("69000"),
                close=Decimal("70500"),
                volume=1000000,
            ),
            CandleDTO(
                timestamp=datetime(2024, 1, 2),
                open=Decimal("70500"),
                high=Decimal("72000"),
                low=Decimal("70000"),
                close=Decimal("71500"),
                volume=1200000,
            ),
        ]

        df = self.loader._candles_to_dataframe(candles)

        assert len(df) == 2
        assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
        assert df.iloc[0]["close"] == 70500.0
        assert df.iloc[1]["volume"] == 1200000

    def test_validate_ohlc_relationship_valid(self):
        """OHLC 관계 검증 (정상) 테스트"""
        df = pd.DataFrame(
            {
                "timestamp": [datetime(2024, 1, 1)],
                "open": [70000],
                "high": [71000],  # 최고가
                "low": [69000],  # 최저가
                "close": [70500],
                "volume": [1000000],
            }
        )

        violations = self.loader._validate_ohlc_relationship(df)
        assert len(violations) == 0

    def test_validate_ohlc_relationship_invalid(self):
        """OHLC 관계 검증 (비정상) 테스트"""
        df = pd.DataFrame(
            {
                "timestamp": [datetime(2024, 1, 1), datetime(2024, 1, 2)],
                "open": [70000, 70000],
                "high": [68000, 71000],  # 첫 번째 행: high < open (비정상)
                "low": [69000, 69000],
                "close": [70500, 70500],
                "volume": [1000000, 1000000],
            }
        )

        violations = self.loader._validate_ohlc_relationship(df)
        assert len(violations) > 0

    def test_validate_data_insufficient(self):
        """데이터 부족 검증 테스트"""
        # 10일 데이터만 (최소 20일 필요)
        df = pd.DataFrame(
            {
                "timestamp": pd.date_range(start="2024-01-01", periods=10),
                "open": [70000] * 10,
                "high": [71000] * 10,
                "low": [69000] * 10,
                "close": [70500] * 10,
                "volume": [1000000] * 10,
            }
        )

        with pytest.raises(BacktestDataError, match="Insufficient data"):
            self.loader._validate_data(
                df, datetime(2024, 1, 1), datetime(2024, 1, 10)
            )

    def test_validate_data_with_null_values(self):
        """결측치 검증 테스트"""
        df = pd.DataFrame(
            {
                "timestamp": pd.date_range(start="2024-01-01", periods=25),
                "open": [70000] * 24 + [None],  # 결측치
                "high": [71000] * 25,
                "low": [69000] * 25,
                "close": [70500] * 25,
                "volume": [1000000] * 25,
            }
        )

        with pytest.raises(BacktestDataError, match="Missing values"):
            self.loader._validate_data(
                df, datetime(2024, 1, 1), datetime(2024, 1, 25)
            )

    def test_validate_data_with_negative_prices(self):
        """음수 가격 검증 테스트"""
        df = pd.DataFrame(
            {
                "timestamp": pd.date_range(start="2024-01-01", periods=25),
                "open": [70000] * 25,
                "high": [71000] * 25,
                "low": [69000] * 24 + [-100],  # 음수 가격
                "close": [70500] * 25,
                "volume": [1000000] * 25,
            }
        )

        with pytest.raises(BacktestDataError, match="Negative or zero prices"):
            self.loader._validate_data(
                df, datetime(2024, 1, 1), datetime(2024, 1, 25)
            )

    def test_validate_data_with_negative_volume(self):
        """음수 거래량 검증 테스트"""
        df = pd.DataFrame(
            {
                "timestamp": pd.date_range(start="2024-01-01", periods=25),
                "open": [70000] * 25,
                "high": [71000] * 25,
                "low": [69000] * 25,
                "close": [70500] * 25,
                "volume": [1000000] * 24 + [-100],  # 음수 거래량
            }
        )

        with pytest.raises(BacktestDataError, match="Negative volume"):
            self.loader._validate_data(
                df, datetime(2024, 1, 1), datetime(2024, 1, 25)
            )

    def test_preprocess_data(self):
        """데이터 전처리 테스트"""
        # 역순 데이터 + 중복
        df = pd.DataFrame(
            {
                "timestamp": [
                    datetime(2024, 1, 3),
                    datetime(2024, 1, 1),
                    datetime(2024, 1, 2),
                    datetime(2024, 1, 2),  # 중복
                ],
                "open": [70000, 70000, 70000, 70000],
                "high": [71000, 71000, 71000, 71000],
                "low": [69000, 69000, 69000, 69000],
                "close": [70500, 70500, 70500, 70500],
                "volume": [1000000, 1000000, 1000000, 1000000],
            }
        )

        processed_df = self.loader._preprocess_data(df)

        # 정렬 확인
        assert processed_df.iloc[0]["timestamp"] == datetime(2024, 1, 1)
        assert processed_df.iloc[1]["timestamp"] == datetime(2024, 1, 2)

        # 중복 제거 확인
        assert len(processed_df) == 3

    def test_validate_missing_dates(self):
        """결측일 검증 테스트"""
        # 2024년 1월 1일(월) ~ 1월 5일(금) 중 1월 3일(수) 데이터 누락
        df = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(
                    [
                        datetime(2024, 1, 1),  # 월
                        datetime(2024, 1, 2),  # 화
                        # 1월 3일(수) 누락
                        datetime(2024, 1, 4),  # 목
                        datetime(2024, 1, 5),  # 금
                    ]
                ),
                "open": [70000] * 4,
                "high": [71000] * 4,
                "low": [69000] * 4,
                "close": [70500] * 4,
                "volume": [1000000] * 4,
            }
        )

        result = self.loader.validate_missing_dates(
            df, datetime(2024, 1, 1), datetime(2024, 1, 5)
        )

        # 기대 거래일: 1/1(월), 1/2(화), 1/3(수), 1/4(목), 1/5(금) = 5일
        # 실제 데이터: 4일
        # 결측일: 1일
        assert result["total_expected"] == 5
        assert result["total_actual"] == 4
        assert result["missing_count"] == 1
        assert result["coverage_rate"] == 0.8

    def test_validate_missing_dates_with_weekends(self):
        """주말 포함 결측일 검증 테스트"""
        # 2024년 1월 1일(월) ~ 1월 7일(일)
        df = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(
                    [
                        datetime(2024, 1, 1),  # 월
                        datetime(2024, 1, 2),  # 화
                        datetime(2024, 1, 3),  # 수
                        datetime(2024, 1, 4),  # 목
                        datetime(2024, 1, 5),  # 금
                        # 1/6(토), 1/7(일) 주말 - 카운트 안 됨
                    ]
                ),
                "open": [70000] * 5,
                "high": [71000] * 5,
                "low": [69000] * 5,
                "close": [70500] * 5,
                "volume": [1000000] * 5,
            }
        )

        result = self.loader.validate_missing_dates(
            df, datetime(2024, 1, 1), datetime(2024, 1, 7)
        )

        # 기대 거래일: 월~금 5일 (주말 제외)
        assert result["total_expected"] == 5
        assert result["total_actual"] == 5
        assert result["missing_count"] == 0
        assert result["coverage_rate"] == 1.0

    def test_get_data_summary(self):
        """데이터 요약 정보 테스트"""
        df = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(
                    [datetime(2024, 1, 1), datetime(2024, 1, 2), datetime(2024, 1, 3)]
                ),
                "open": [70000, 71000, 72000],
                "high": [71000, 72000, 73000],
                "low": [69000, 70000, 71000],
                "close": [70500, 71500, 72500],
                "volume": [1000000, 1200000, 1100000],
            }
        )

        summary = self.loader.get_data_summary(df)

        assert summary["total_rows"] == 3
        assert summary["start_date"] == pd.Timestamp(datetime(2024, 1, 1))
        assert summary["end_date"] == pd.Timestamp(datetime(2024, 1, 3))
        assert summary["price_min"] == 69000
        assert summary["price_max"] == 73000
        assert summary["avg_volume"] == 1100000  # (1000000 + 1200000 + 1100000) / 3

    def test_preprocess_data_with_forward_fill(self):
        """Forward Fill 전처리 테스트"""
        df = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(
                    [datetime(2024, 1, 1), datetime(2024, 1, 2), datetime(2024, 1, 3)]
                ),
                "open": [70000, None, 72000],  # 결측치
                "high": [71000, None, 73000],
                "low": [69000, None, 71000],
                "close": [70500, None, 72500],
                "volume": [1000000, None, 1100000],
            }
        )

        processed_df = self.loader._preprocess_data(df)

        # Forward Fill 확인 (None -> 이전 값)
        assert processed_df.iloc[1]["open"] == 70000.0
        assert processed_df.iloc[1]["close"] == 70500.0
