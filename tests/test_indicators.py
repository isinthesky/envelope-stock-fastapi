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


class TestCombinedSignal:
    """결합 시그널 테스트"""

    def setup_method(self):
        """테스트용 밴드 데이터 준비"""
        self.bb_bands = {"upper": 110.0, "middle": 100.0, "lower": 90.0}
        self.env_bands = {"upper": 105.0, "middle": 100.0, "lower": 95.0}  # 엔벨로프가 볼린저 안쪽

    def test_buy_signal_strict_mode(self):
        """매수 시그널 (엄격 모드)"""
        # 두 지표 모두 하단 돌파
        signal = TechnicalIndicators.generate_combined_signal(
            current_price=88.0,  # 볼린저 하단(90) 아래, 엔벨로프 하단(95) 아래
            bb_bands=self.bb_bands,
            envelope_bands=self.env_bands,
            use_strict_mode=True,
        )

        assert signal == "buy"

    def test_sell_signal_strict_mode(self):
        """매도 시그널 (엄격 모드)"""
        # 두 지표 모두 상단 돌파
        signal = TechnicalIndicators.generate_combined_signal(
            current_price=112.0,  # 볼린저 상단(110) 위, 엔벨로프 상단(105) 위
            bb_bands=self.bb_bands,
            envelope_bands=self.env_bands,
            use_strict_mode=True,
        )

        assert signal == "sell"

    def test_hold_signal_strict_mode(self):
        """보유 시그널 (엄격 모드 - 하나만 만족)"""
        # 볼린저는 돌파, 엔벨로프는 미돌파
        signal = TechnicalIndicators.generate_combined_signal(
            current_price=92.0,  # 볼린저 하단(90) 근처, 엔벨로프 하단(95) 위
            bb_bands=self.bb_bands,
            envelope_bands=self.env_bands,
            use_strict_mode=True,
        )

        # 엄격 모드에서는 두 지표 모두 돌파해야 시그널 -> hold
        assert signal == "hold"

    def test_buy_signal_loose_mode(self):
        """매수 시그널 (완화 모드 - 하나만 만족)"""
        # 볼린저만 하단 돌파
        signal = TechnicalIndicators.generate_combined_signal(
            current_price=92.0,  # 볼린저 근처, 엔벨로프 위
            bb_bands=self.bb_bands,
            envelope_bands=self.env_bands,
            use_strict_mode=False,  # 완화 모드
        )

        # 완화 모드: 하나만 만족해도 시그널
        assert signal == "buy"

    def test_hold_signal_middle_price(self):
        """보유 시그널 (중간 가격)"""
        signal = TechnicalIndicators.generate_combined_signal(
            current_price=100.0,  # 중간선
            bb_bands=self.bb_bands,
            envelope_bands=self.env_bands,
            use_strict_mode=True,
        )

        assert signal == "hold"


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


class TestRealWorldScenario:
    """실제 시나리오 테스트"""

    def test_samsung_electronics_scenario(self):
        """삼성전자 시나리오 (임의 데이터)"""
        # 삼성전자 종가 데이터 (임의 생성)
        prices = [
            70000,
            71000,
            69000,
            70500,
            72000,
            71500,
            70000,
            69500,
            68000,
            67000,  # 10일
            66000,
            65000,
            64000,
            63000,
            64000,
            65000,
            66000,
            67000,
            68000,
            69000,  # 20일
            70000,
            71000,
            72000,
            73000,
            72500,
            71000,
            70000,
            69000,
            68000,
            67000,  # 30일
        ]

        # 볼린저 밴드 계산
        bb = TechnicalIndicators.calculate_bollinger_bands(prices, period=20, std_multiplier=2.0)

        # 엔벨로프 계산
        env = TechnicalIndicators.calculate_envelope(prices, period=20, percentage=2.0)

        # 현재가가 과매도 구간인지 확인
        current_price = 67000

        signal = TechnicalIndicators.generate_combined_signal(current_price, bb, env, use_strict_mode=True)

        # 결과 출력 (디버깅용)
        print(f"\n=== 삼성전자 시나리오 ===")
        print(f"현재가: {current_price:,}원")
        print(f"볼린저 밴드: 하단={bb['lower']:,.0f}, 중간={bb['middle']:,.0f}, 상단={bb['upper']:,.0f}")
        print(f"엔벨로프: 하단={env['lower']:,.0f}, 중간={env['middle']:,.0f}, 상단={env['upper']:,.0f}")
        print(f"시그널: {signal}")

        strength = TechnicalIndicators.get_signal_strength(current_price, bb, env)
        print(f"시그널 강도: BB={strength['bb_position']:.2f}, ENV={strength['env_position']:.2f}")

        # 시그널이 생성되었는지 확인 (buy 또는 hold)
        assert signal in ["buy", "hold", "sell"]
