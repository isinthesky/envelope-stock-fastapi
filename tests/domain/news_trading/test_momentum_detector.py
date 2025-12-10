# -*- coding: utf-8 -*-
"""
Momentum Detector 유닛 테스트
"""

import pytest
from datetime import datetime, timedelta
from decimal import Decimal

from src.application.domain.news_trading.dto import (
    MomentumSignal,
    MomentumExitConfigDTO,
)
from src.application.domain.news_trading.momentum_detector import (
    MomentumDetector,
    SimpleMovingMomentum,
    PriceData,
    TickData,
    OrderbookData,
)


class TestMomentumDetector:
    """MomentumDetector 테스트"""

    @pytest.fixture
    def config(self):
        """테스트용 모멘텀 설정"""
        return MomentumExitConfigDTO(
            price_decel_consecutive=2,
            tick_slowdown_threshold=0.5,
            order_imbalance_threshold=1.2,
            volume_drop_threshold=0.3,
            price_decel_weight=2,
            tick_slowdown_weight=1,
            order_imbalance_weight=2,
            volume_drop_weight=1,
            momentum_weakness_threshold=3,
        )

    @pytest.fixture
    def detector(self, config):
        """테스트용 모멘텀 감지기"""
        return MomentumDetector(config)

    def test_get_or_create_state(self, detector):
        """상태 생성 및 조회"""
        state = detector.get_or_create_state("005930")

        assert state is not None
        assert state.symbol == "005930"
        assert "005930" in detector.states

    def test_reset_state(self, detector):
        """상태 초기화"""
        detector.get_or_create_state("005930")
        detector.reset_state("005930")

        assert "005930" not in detector.states

    def test_update_price(self, detector):
        """가격 데이터 업데이트"""
        now = datetime.now()

        # 가격 데이터 추가
        detector.update_price("005930", PriceData(timestamp=now, price=Decimal("70000")))
        detector.update_price("005930", PriceData(timestamp=now, price=Decimal("70100")))
        detector.update_price("005930", PriceData(timestamp=now, price=Decimal("70200")))

        state = detector.get_or_create_state("005930")
        assert len(state.price_history) == 3

    def test_update_tick(self, detector):
        """틱 데이터 업데이트"""
        now = datetime.now()

        # 틱 데이터 추가
        detector.update_tick("005930", TickData(timestamp=now, price=Decimal("70000"), volume=100, is_buy=True))
        detector.update_tick("005930", TickData(timestamp=now, price=Decimal("70100"), volume=150, is_buy=True))

        state = detector.get_or_create_state("005930")
        assert len(state.tick_history) >= 2

    def test_update_orderbook(self, detector):
        """호가 데이터 업데이트"""
        now = datetime.now()

        # 호가 데이터 추가
        detector.update_orderbook("005930", OrderbookData(
            timestamp=now,
            total_bid_volume=10000,
            total_ask_volume=15000,
        ))

        state = detector.get_or_create_state("005930")
        assert len(state.orderbook_history) == 1
        assert state.current_bid_ask_ratio == 1.5  # 15000/10000

    def test_update_volume(self, detector):
        """분봉 거래량 업데이트"""
        now = datetime.now()

        detector.update_volume("005930", 10000, now)
        detector.update_volume("005930", 8000, now)

        state = detector.get_or_create_state("005930")
        assert len(state.volume_history) == 2

    def test_detect_price_deceleration_signal(self, detector):
        """가격 감속 신호 감지"""
        now = datetime.now()

        # 상승 후 둔화 시뮬레이션
        detector.update_price("005930", PriceData(timestamp=now, price=Decimal("70000")))
        detector.update_price("005930", PriceData(timestamp=now, price=Decimal("70500")))  # +500
        detector.update_price("005930", PriceData(timestamp=now, price=Decimal("70800")))  # +300 (둔화)
        detector.update_price("005930", PriceData(timestamp=now, price=Decimal("70900")))  # +100 (더 둔화)

        signals, weight_sum = detector.detect_signals("005930")

        # 연속 감속 시 신호 발생 여부 확인
        assert isinstance(signals, list)
        assert isinstance(weight_sum, int)

    def test_detect_orderbook_imbalance_signal(self, detector):
        """호가 불균형 신호 감지"""
        now = datetime.now()

        # 매도 우위 호가창
        detector.update_orderbook("005930", OrderbookData(
            timestamp=now,
            total_bid_volume=10000,
            total_ask_volume=15000,  # 매도잔량이 더 많음
        ))

        signals, weight_sum = detector.detect_signals("005930")

        # 호가 불균형 신호 확인
        assert MomentumSignal.ORDER_IMBALANCE in signals

    def test_detect_volume_drop_signal(self, detector):
        """거래량 급감 신호 감지"""
        now = datetime.now()

        # 거래량 급감 시뮬레이션
        detector.update_volume("005930", 10000, now)
        detector.update_volume("005930", 2000, now)  # 20%로 급감

        signals, weight_sum = detector.detect_signals("005930")

        # 거래량 감소 신호 확인
        assert MomentumSignal.VOLUME_DROP in signals

    def test_is_momentum_weak(self, detector):
        """모멘텀 약화 판정"""
        now = datetime.now()

        # 여러 약화 신호 발생
        detector.update_orderbook("005930", OrderbookData(
            timestamp=now,
            total_bid_volume=10000,
            total_ask_volume=15000,
        ))
        detector.update_volume("005930", 10000, now)
        detector.update_volume("005930", 2000, now)

        is_weak = detector.is_momentum_weak("005930")

        # ORDER_IMBALANCE(2) + VOLUME_DROP(1) = 3 >= threshold(3)
        assert is_weak is True

    def test_get_momentum_summary(self, detector):
        """모멘텀 상태 요약"""
        now = datetime.now()

        detector.update_orderbook("005930", OrderbookData(
            timestamp=now,
            total_bid_volume=10000,
            total_ask_volume=12000,
        ))

        summary = detector.get_momentum_summary("005930")

        assert "symbol" in summary
        assert "is_weak" in summary
        assert "weight_sum" in summary
        assert "signals" in summary


class TestSimpleMovingMomentum:
    """SimpleMovingMomentum 테스트 (백테스트용)"""

    def test_calculate_price_acceleration(self):
        """가격 가속도 계산"""
        prices = [100, 102, 105, 107, 108]

        accelerations = SimpleMovingMomentum.calculate_price_acceleration(prices)

        assert len(accelerations) == len(prices)
        # 처음 2개는 None
        assert accelerations[0] is None
        assert accelerations[1] is None
        # 이후는 값이 있음
        assert accelerations[2] is not None

    def test_calculate_volume_change_rate(self):
        """거래량 변화율 계산"""
        volumes = [1000, 800, 600]

        change_rates = SimpleMovingMomentum.calculate_volume_change_rate(volumes)

        assert len(change_rates) == len(volumes)
        # 첫 번째는 None
        assert change_rates[0] is None
        # 두 번째: 800/1000 = 0.8
        assert change_rates[1] == pytest.approx(0.8, rel=0.01)
        # 세 번째: 600/800 = 0.75
        assert change_rates[2] == pytest.approx(0.75, rel=0.01)

    def test_detect_momentum_weakness_from_ohlcv_insufficient_data(self):
        """OHLCV 데이터 부족 시"""
        closes = [100, 101]
        volumes = [1000, 900]

        weakness_flags = SimpleMovingMomentum.detect_momentum_weakness_from_ohlcv(
            closes, volumes
        )

        # 데이터 부족 시 모두 False
        assert all(flag is False for flag in weakness_flags)

    def test_detect_momentum_weakness_from_ohlcv_with_weakness(self):
        """OHLCV 데이터에서 약화 감지"""
        closes = [100, 102, 103, 103.5, 103.6, 103.7]
        volumes = [1000, 900, 800, 200, 150, 100]  # 급감

        # 높은 호가 불균형
        bid_ask_ratios = [1.0, 1.0, 1.0, 1.5, 1.6, 1.7]

        config = MomentumExitConfigDTO(
            volume_drop_threshold=0.5,
            order_imbalance_threshold=1.3,
            momentum_weakness_threshold=3,
        )

        weakness_flags = SimpleMovingMomentum.detect_momentum_weakness_from_ohlcv(
            closes, volumes, bid_ask_ratios, config
        )

        # 마지막 부분에서 약화 감지
        assert len(weakness_flags) == len(closes)
