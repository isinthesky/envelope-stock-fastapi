# -*- coding: utf-8 -*-
"""
Momentum Detector - 모멘텀 감지 모듈

Phase 2 (cross_pollination.md) + Phase 4 (Task 4) 기반:
- 가격 가속도 감지 (PRICE_DECEL)
- 체결 속도 감지 (TICK_SLOWDOWN)
- 호가 불균형 감지 (ORDER_IMBALANCE)
- 거래량 감소 감지 (VOLUME_DROP)
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from src.application.domain.news_trading.dto import (
    MomentumSignal,
    MomentumExitConfigDTO,
)


@dataclass
class PriceData:
    """가격 데이터"""
    timestamp: datetime
    price: Decimal
    volume: int = 0


@dataclass
class OrderbookData:
    """호가 데이터"""
    timestamp: datetime
    total_bid_volume: int  # 총 매수잔량
    total_ask_volume: int  # 총 매도잔량


@dataclass
class TickData:
    """체결 데이터"""
    timestamp: datetime
    price: Decimal
    volume: int
    is_buy: bool  # 매수 체결 여부


@dataclass
class MomentumState:
    """모멘텀 상태"""
    symbol: str

    # 가격 가속도 관련
    price_history: list[PriceData] = field(default_factory=list)
    price_acceleration_history: list[float] = field(default_factory=list)
    consecutive_decel_count: int = 0

    # 체결 속도 관련
    tick_history: list[TickData] = field(default_factory=list)
    recent_tick_rate: float = 0.0  # 최근 30초 체결 건수/초
    prev_tick_rate: float = 0.0  # 이전 30초 체결 건수/초

    # 호가 관련
    orderbook_history: list[OrderbookData] = field(default_factory=list)
    current_bid_ask_ratio: float = 1.0

    # 거래량 관련
    volume_history: list[int] = field(default_factory=list)  # 분봉 거래량

    # 감지된 신호
    active_signals: list[MomentumSignal] = field(default_factory=list)
    signal_weight_sum: int = 0

    # 마지막 업데이트 시각
    last_updated: datetime | None = None


class MomentumDetector:
    """
    모멘텀 감지기

    주요 기능:
    1. 가격 가속도 감지 (연속 N회 하락)
    2. 체결 속도 감지 (이전 대비 50% 이하)
    3. 호가 불균형 감지 (매도잔량 > 매수잔량)
    4. 거래량 감소 감지 (이전 대비 30% 이하)
    5. 모멘텀 약화 종합 판정
    """

    def __init__(self, config: MomentumExitConfigDTO | None = None):
        """
        Args:
            config: 모멘텀 감지 설정 (None이면 기본값 사용)
        """
        self.config = config or MomentumExitConfigDTO()
        self.states: dict[str, MomentumState] = {}

    def get_or_create_state(self, symbol: str) -> MomentumState:
        """종목별 모멘텀 상태 조회 또는 생성"""
        if symbol not in self.states:
            self.states[symbol] = MomentumState(symbol=symbol)
        return self.states[symbol]

    def reset_state(self, symbol: str) -> None:
        """종목별 모멘텀 상태 초기화"""
        if symbol in self.states:
            del self.states[symbol]

    def update_price(self, symbol: str, price_data: PriceData) -> None:
        """
        가격 데이터 업데이트 및 가속도 계산

        가속도 = (현재 변화율) - (이전 변화율)
        """
        state = self.get_or_create_state(symbol)
        state.price_history.append(price_data)
        state.last_updated = price_data.timestamp

        # 최근 20개만 유지
        if len(state.price_history) > 20:
            state.price_history = state.price_history[-20:]

        # 가속도 계산 (최소 3개 데이터 필요)
        if len(state.price_history) >= 3:
            prices = [float(p.price) for p in state.price_history]

            # 변화율 계산
            prev_change = (prices[-2] - prices[-3]) / prices[-3] if prices[-3] > 0 else 0
            curr_change = (prices[-1] - prices[-2]) / prices[-2] if prices[-2] > 0 else 0

            # 가속도 = 현재 변화율 - 이전 변화율
            acceleration = curr_change - prev_change
            state.price_acceleration_history.append(acceleration)

            # 최근 10개만 유지
            if len(state.price_acceleration_history) > 10:
                state.price_acceleration_history = state.price_acceleration_history[-10:]

            # 연속 하락 카운트
            if acceleration < 0:
                state.consecutive_decel_count += 1
            else:
                state.consecutive_decel_count = 0

    def update_tick(self, symbol: str, tick_data: TickData) -> None:
        """체결 데이터 업데이트 및 체결 속도 계산"""
        state = self.get_or_create_state(symbol)
        state.tick_history.append(tick_data)
        state.last_updated = tick_data.timestamp

        # 최근 60초 데이터만 유지
        cutoff_time = tick_data.timestamp.timestamp() - 60
        state.tick_history = [
            t for t in state.tick_history
            if t.timestamp.timestamp() > cutoff_time
        ]

        # 체결 속도 계산 (30초 기준)
        now = tick_data.timestamp.timestamp()
        recent_ticks = [
            t for t in state.tick_history
            if t.timestamp.timestamp() > now - 30
        ]
        older_ticks = [
            t for t in state.tick_history
            if now - 60 < t.timestamp.timestamp() <= now - 30
        ]

        state.prev_tick_rate = len(older_ticks) / 30 if older_ticks else 0
        state.recent_tick_rate = len(recent_ticks) / 30 if recent_ticks else 0

    def update_orderbook(self, symbol: str, orderbook_data: OrderbookData) -> None:
        """호가 데이터 업데이트"""
        state = self.get_or_create_state(symbol)
        state.orderbook_history.append(orderbook_data)
        state.last_updated = orderbook_data.timestamp

        # 최근 10개만 유지
        if len(state.orderbook_history) > 10:
            state.orderbook_history = state.orderbook_history[-10:]

        # 매수/매도 잔량 비율 계산
        if orderbook_data.total_bid_volume > 0:
            state.current_bid_ask_ratio = (
                orderbook_data.total_ask_volume / orderbook_data.total_bid_volume
            )
        else:
            state.current_bid_ask_ratio = float("inf")

    def update_volume(self, symbol: str, volume: int, timestamp: datetime) -> None:
        """분봉 거래량 업데이트"""
        state = self.get_or_create_state(symbol)
        state.volume_history.append(volume)
        state.last_updated = timestamp

        # 최근 10개만 유지
        if len(state.volume_history) > 10:
            state.volume_history = state.volume_history[-10:]

    def detect_signals(self, symbol: str) -> tuple[list[MomentumSignal], int]:
        """
        모멘텀 약화 신호 감지

        Returns:
            (감지된 신호 목록, 신호 가중치 합)
        """
        state = self.get_or_create_state(symbol)
        signals: list[MomentumSignal] = []
        weight_sum = 0

        # 1. 가격 가속도 감소 (PRICE_DECEL)
        if state.consecutive_decel_count >= self.config.price_decel_consecutive:
            signals.append(MomentumSignal.PRICE_DECEL)
            weight_sum += self.config.price_decel_weight

        # 2. 체결 속도 감소 (TICK_SLOWDOWN)
        if state.prev_tick_rate > 0:
            tick_ratio = state.recent_tick_rate / state.prev_tick_rate
            if tick_ratio < self.config.tick_slowdown_threshold:
                signals.append(MomentumSignal.TICK_SLOWDOWN)
                weight_sum += self.config.tick_slowdown_weight

        # 3. 호가 불균형 (ORDER_IMBALANCE) - 매도 > 매수
        if state.current_bid_ask_ratio >= self.config.order_imbalance_threshold:
            signals.append(MomentumSignal.ORDER_IMBALANCE)
            weight_sum += self.config.order_imbalance_weight

        # 4. 거래량 감소 (VOLUME_DROP)
        if len(state.volume_history) >= 2:
            prev_volume = state.volume_history[-2]
            curr_volume = state.volume_history[-1]
            if prev_volume > 0:
                volume_ratio = curr_volume / prev_volume
                if volume_ratio < self.config.volume_drop_threshold:
                    signals.append(MomentumSignal.VOLUME_DROP)
                    weight_sum += self.config.volume_drop_weight

        # 상태 업데이트
        state.active_signals = signals
        state.signal_weight_sum = weight_sum

        return signals, weight_sum

    def is_momentum_weak(self, symbol: str) -> bool:
        """
        모멘텀 약화 여부 판정

        가중치 합 >= threshold이면 모멘텀 약화로 판정
        """
        signals, weight_sum = self.detect_signals(symbol)
        return weight_sum >= self.config.momentum_weakness_threshold

    def get_momentum_summary(self, symbol: str) -> dict[str, Any]:
        """모멘텀 상태 요약"""
        state = self.get_or_create_state(symbol)
        signals, weight_sum = self.detect_signals(symbol)

        return {
            "symbol": symbol,
            "is_weak": weight_sum >= self.config.momentum_weakness_threshold,
            "weight_sum": weight_sum,
            "threshold": self.config.momentum_weakness_threshold,
            "signals": [s.value for s in signals],
            "consecutive_decel_count": state.consecutive_decel_count,
            "tick_rate_ratio": (
                state.recent_tick_rate / state.prev_tick_rate
                if state.prev_tick_rate > 0
                else None
            ),
            "bid_ask_ratio": state.current_bid_ask_ratio,
            "last_updated": state.last_updated.isoformat() if state.last_updated else None,
        }

    def get_all_states(self) -> dict[str, MomentumState]:
        """모든 종목의 모멘텀 상태 조회"""
        return self.states.copy()


class SimpleMovingMomentum:
    """
    단순 이동 모멘텀 계산기

    분봉 데이터 기반 모멘텀 계산 (백테스트용)
    """

    @staticmethod
    def calculate_price_acceleration(
        prices: list[float], window: int = 3
    ) -> list[float | None]:
        """
        가격 가속도 계산

        Args:
            prices: 가격 리스트
            window: 계산 윈도우 (최소 3)

        Returns:
            가속도 리스트 (처음 window-1개는 None)
        """
        if len(prices) < window:
            return [None] * len(prices)

        accelerations: list[float | None] = [None] * (window - 1)

        for i in range(window - 1, len(prices)):
            # 이전 변화율
            prev_change = (prices[i - 1] - prices[i - 2]) / prices[i - 2] if prices[i - 2] > 0 else 0
            # 현재 변화율
            curr_change = (prices[i] - prices[i - 1]) / prices[i - 1] if prices[i - 1] > 0 else 0
            # 가속도
            accelerations.append(curr_change - prev_change)

        return accelerations

    @staticmethod
    def calculate_volume_change_rate(
        volumes: list[int], window: int = 2
    ) -> list[float | None]:
        """
        거래량 변화율 계산

        Args:
            volumes: 거래량 리스트
            window: 비교 윈도우

        Returns:
            변화율 리스트 (처음 window-1개는 None)
        """
        if len(volumes) < window:
            return [None] * len(volumes)

        change_rates: list[float | None] = [None] * (window - 1)

        for i in range(window - 1, len(volumes)):
            prev_vol = volumes[i - 1]
            curr_vol = volumes[i]
            if prev_vol > 0:
                change_rates.append(curr_vol / prev_vol)
            else:
                change_rates.append(None)

        return change_rates

    @staticmethod
    def detect_momentum_weakness_from_ohlcv(
        closes: list[float],
        volumes: list[int],
        bid_ask_ratios: list[float] | None = None,
        config: MomentumExitConfigDTO | None = None,
    ) -> list[bool]:
        """
        OHLCV 데이터에서 모멘텀 약화 감지 (백테스트용)

        Args:
            closes: 종가 리스트
            volumes: 거래량 리스트
            bid_ask_ratios: 매도/매수 잔량 비율 리스트 (선택)
            config: 모멘텀 설정

        Returns:
            모멘텀 약화 여부 리스트
        """
        config = config or MomentumExitConfigDTO()
        n = len(closes)

        if n < 3:
            return [False] * n

        # 가속도 계산
        accelerations = SimpleMovingMomentum.calculate_price_acceleration(closes)

        # 거래량 변화율 계산
        volume_changes = SimpleMovingMomentum.calculate_volume_change_rate(volumes)

        # 호가 비율 (없으면 기본값)
        if bid_ask_ratios is None:
            bid_ask_ratios = [1.0] * n

        weakness_flags: list[bool] = []

        for i in range(n):
            weight_sum = 0

            # 가격 가속도 신호
            if i >= config.price_decel_consecutive:
                recent_accel = accelerations[i - config.price_decel_consecutive + 1 : i + 1]
                if all(a is not None and a < 0 for a in recent_accel):
                    weight_sum += config.price_decel_weight

            # 거래량 감소 신호
            if volume_changes[i] is not None:
                if volume_changes[i] < config.volume_drop_threshold:
                    weight_sum += config.volume_drop_weight

            # 호가 불균형 신호
            if bid_ask_ratios[i] >= config.order_imbalance_threshold:
                weight_sum += config.order_imbalance_weight

            # 모멘텀 약화 판정
            weakness_flags.append(weight_sum >= config.momentum_weakness_threshold)

        return weakness_flags
