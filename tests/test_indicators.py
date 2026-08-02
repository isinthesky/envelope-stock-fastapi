# -*- coding: utf-8 -*-
"""
Technical Indicators 테스트
"""

import pytest

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


class TestEnvelope:
    """엔벨로프 테스트"""

    def test_calculate_envelope_normal(self):
        """정상적인 엔벨로프 계산"""
        prices = [100, 102, 98, 101, 99, 103, 97, 102, 100, 101] * 3

        env = TechnicalIndicators.calculate_envelope(prices, period=20, percentage=2.0)

        assert env["upper"] is not None
        assert env["middle"] is not None
        assert env["lower"] is not None
        assert env["upper"] > env["middle"] > env["lower"]

        # 2% 채널 확인
        expected_upper = env["middle"] * 1.02
        expected_lower = env["middle"] / 1.02
        assert abs(env["upper"] - expected_upper) < 0.01
        assert abs(env["lower"] - expected_lower) < 0.01


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


class TestSignalStrength:
    """시그널 강도 테스트"""

    def test_signal_strength_at_middle(self):
        """중간선에서 강도 0"""
        bb_bands = {"upper": 110.0, "middle": 100.0, "lower": 90.0}
        env_bands = {"upper": 102.0, "middle": 100.0, "lower": 98.0}

        strength = TechnicalIndicators.get_signal_strength(current_price=100.0, bb_bands=bb_bands, envelope_bands=env_bands)

        assert strength["bb_position"] == 0.0
        assert strength["env_position"] == 0.0

    def test_signal_strength_at_upper(self):
        """상단 밴드에서 강도 +1"""
        bb_bands = {"upper": 110.0, "middle": 100.0, "lower": 90.0}
        env_bands = {"upper": 102.0, "middle": 100.0, "lower": 98.0}

        strength = TechnicalIndicators.get_signal_strength(current_price=110.0, bb_bands=bb_bands, envelope_bands=env_bands)

        assert strength["bb_position"] == pytest.approx(1.0, abs=0.01)

    def test_signal_strength_at_lower(self):
        """하단 밴드에서 강도 -1"""
        bb_bands = {"upper": 110.0, "middle": 100.0, "lower": 90.0}
        env_bands = {"upper": 102.0, "middle": 100.0, "lower": 98.0}

        strength = TechnicalIndicators.get_signal_strength(current_price=90.0, bb_bands=bb_bands, envelope_bands=env_bands)

        assert strength["bb_position"] == pytest.approx(-1.0, abs=0.01)

    def test_signal_strength_extreme_oversold(self):
        """극단적 과매도 (하단 훨씬 아래)"""
        bb_bands = {"upper": 110.0, "middle": 100.0, "lower": 90.0}
        env_bands = {"upper": 102.0, "middle": 100.0, "lower": 98.0}

        strength = TechnicalIndicators.get_signal_strength(current_price=70.0, bb_bands=bb_bands, envelope_bands=env_bands)

        # -2 이하로 제한
        assert strength["bb_position"] <= -2.0
        assert strength["env_position"] <= -2.0
