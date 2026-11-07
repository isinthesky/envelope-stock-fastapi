# -*- coding: utf-8 -*-
"""
Technical Indicators 테스트
"""


from src.application.common.indicators import TechnicalIndicators


class TestBollingerBands:
    """볼린저 밴드 테스트"""

    def test_calculate_bollinger_bands_normal(self):
        """정상적인 볼린저 밴드 계산"""
        prices = [100, 102, 98, 101, 99, 103, 97, 102, 100, 101] * 3  # 30일 데이터

        bb = TechnicalIndicators.calculate_bollinger_bands(prices, period=20, std_multiplier=2.0)

        assert bb["upper"] is not None
        assert bb["middle"] is not None
        assert bb["lower"] is not None
        assert bb["upper"] > bb["middle"] > bb["lower"]

    def test_calculate_bollinger_bands_insufficient_data(self):
        """데이터 부족 시 None 반환"""
        prices = [100, 102, 98]  # 3일만

        bb = TechnicalIndicators.calculate_bollinger_bands(prices, period=20)

        assert bb["upper"] is None
        assert bb["middle"] is None
        assert bb["lower"] is None


class TestStochastic:
    """Stochastic oscillator input validation tests."""

    def test_returns_none_for_misaligned_ohlcv_lists(self):
        """Mismatched OHLCV rows must not cause DataFrame construction errors."""
        stoch_k, stoch_d = TechnicalIndicators.calculate_stochastic_from_prices(
            closes=[100.0] * 17,
            highs=[101.0] * 16,
            lows=[99.0] * 17,
            k_period=14,
            d_period=3,
        )

        assert stoch_k is None
        assert stoch_d is None

