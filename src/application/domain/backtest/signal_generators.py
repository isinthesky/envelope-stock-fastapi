# -*- coding: utf-8 -*-
"""
Signal Generators - 백테스트용 시그널 생성기

전략별 매수/매도 시그널 생성 로직
"""

from abc import ABC, abstractmethod
from decimal import Decimal

from src.application.common.indicators import TechnicalIndicators
from src.application.domain.strategy.strategy_contract import (
    DEFAULT_GOLDEN_CROSS_PULLBACK,
    GoldenCrossTradeSignal,
)


class BaseSignalGenerator(ABC):
    @abstractmethod
    def generate_signal(
        self,
        price_history: list[float],
        current_price: Decimal,
        **kwargs: object,
    ) -> str:
        pass

    @property
    @abstractmethod
    def min_period(self) -> int:
        pass

    def reset(self) -> None:
        pass


class BollingerEnvelopeSignalGenerator(BaseSignalGenerator):
    def __init__(
        self,
        bb_period: int = 20,
        bb_std_multiplier: float = 2.0,
        env_period: int = 20,
        env_percentage: float = 2.0,
        use_strict_mode: bool = True,
    ):
        self.bb_period = bb_period
        self.bb_std_multiplier = bb_std_multiplier
        self.env_period = env_period
        self.env_percentage = env_percentage
        self.use_strict_mode = use_strict_mode

    @property
    def min_period(self) -> int:
        return max(self.bb_period, self.env_period)

    def generate_signal(
        self,
        price_history: list[float],
        current_price: Decimal,
        **kwargs: object,
    ) -> str:
        if len(price_history) < self.min_period:
            return "hold"
        bb_bands = TechnicalIndicators.calculate_bollinger_bands(
            price_history, period=self.bb_period, std_multiplier=self.bb_std_multiplier
        )
        env_bands = TechnicalIndicators.calculate_envelope(
            price_history, period=self.env_period, percentage=self.env_percentage
        )
        return TechnicalIndicators.generate_combined_signal(
            current_price=float(current_price),
            bb_bands=bb_bands,
            envelope_bands=env_bands,
            use_strict_mode=self.use_strict_mode,
        )


class GoldenCrossSignalGenerator(BaseSignalGenerator):
    """스윙형 골든크로스 시그널 생성기"""

    def __init__(
        self,
        short_period: int = DEFAULT_GOLDEN_CROSS_PULLBACK.short_period,
        long_period: int = DEFAULT_GOLDEN_CROSS_PULLBACK.long_period,
        stoch_k_period: int = DEFAULT_GOLDEN_CROSS_PULLBACK.stoch_k_period,
        stoch_d_period: int = DEFAULT_GOLDEN_CROSS_PULLBACK.stoch_d_period,
        stoch_oversold: float = DEFAULT_GOLDEN_CROSS_PULLBACK.oversold_threshold,
        stoch_overbought: float = 70.0,
        require_k_above_d_for_buy: bool = False,
        require_k_below_d_for_sell: bool = False,
        buy_recovery_threshold: float = DEFAULT_GOLDEN_CROSS_PULLBACK.strong_recovery_threshold,
        min_pullback_bars: int = DEFAULT_GOLDEN_CROSS_PULLBACK.min_pullback_bars,
        min_reentry_cooldown_bars: int = DEFAULT_GOLDEN_CROSS_PULLBACK.min_reentry_cooldown_bars,
        disable_stoch_overbought_sell: bool = True,
    ):
        self.short_period = short_period
        self.long_period = long_period
        self.stoch_k_period = stoch_k_period
        self.stoch_d_period = stoch_d_period
        self.stoch_oversold = stoch_oversold
        self.stoch_overbought = stoch_overbought
        self.require_k_above_d_for_buy = require_k_above_d_for_buy
        self.require_k_below_d_for_sell = require_k_below_d_for_sell
        self.buy_recovery_threshold = buy_recovery_threshold
        self.min_pullback_bars = min_pullback_bars
        self.min_reentry_cooldown_bars = min_reentry_cooldown_bars
        self.disable_stoch_overbought_sell = disable_stoch_overbought_sell
        self._prev_stoch_k: float | None = None
        self._prev_stoch_d: float | None = None
        self._oversold_seen = False
        self._pullback_bars = 0
        self._bars_since_exit = 999999

    @property
    def min_period(self) -> int:
        return self.long_period

    def generate_signal(
        self,
        price_history: list[float],
        current_price: Decimal,
        high_history: list[float] | None = None,
        low_history: list[float] | None = None,
        close_history: list[float] | None = None,
        **kwargs: object,
    ) -> str:
        if len(price_history) < self.min_period:
            return GoldenCrossTradeSignal.HOLD.value
        self._bars_since_exit += 1
        ma_short = self._calculate_sma(price_history, self.short_period)
        ma_long = self._calculate_sma(price_history, self.long_period)
        stoch_k, stoch_d = self._calculate_stochastic(
            close_history or price_history,
            high_history=high_history,
            low_history=low_history,
        )
        is_gc_active = ma_short > ma_long
        is_death_cross = ma_short < ma_long
        if stoch_k < self.stoch_oversold:
            self._oversold_seen = True
            self._pullback_bars += 1
        elif self._oversold_seen and stoch_k < self.buy_recovery_threshold:
            self._pullback_bars += 1

        if self._should_sell(is_death_cross, stoch_k, stoch_d):
            self._bars_since_exit = 0
            self._oversold_seen = False
            self._pullback_bars = 0
            return GoldenCrossTradeSignal.SELL.value
        if self._should_buy(is_gc_active, stoch_k, stoch_d):
            self._oversold_seen = False
            self._pullback_bars = 0
            return GoldenCrossTradeSignal.BUY.value
        self._prev_stoch_k = stoch_k
        self._prev_stoch_d = stoch_d
        return GoldenCrossTradeSignal.HOLD.value

    def _should_buy(self, is_gc_active: bool, stoch_k: float, stoch_d: float) -> bool:
        if not is_gc_active:
            self._oversold_seen = False
            self._pullback_bars = 0
            return False
        if self._bars_since_exit < self.min_reentry_cooldown_bars:
            return False
        if not self._oversold_seen:
            return False
        if self._pullback_bars < self.min_pullback_bars:
            return False
        if stoch_k < self.buy_recovery_threshold:
            return False
        if self.require_k_above_d_for_buy and stoch_k <= stoch_d:
            return False
        if self._prev_stoch_k is not None and stoch_k <= self._prev_stoch_k:
            return False
        return True

    def _should_sell(self, is_death_cross: bool, stoch_k: float, stoch_d: float) -> bool:
        if is_death_cross:
            return True
        if self.disable_stoch_overbought_sell:
            return False
        if stoch_k > self.stoch_overbought:
            if self.require_k_below_d_for_sell and stoch_k >= stoch_d:
                return False
            return True
        return False

    def _calculate_sma(self, prices: list[float], period: int) -> float:
        if len(prices) < period:
            return 0.0
        return sum(prices[-period:]) / period

    def _calculate_stochastic(
        self,
        prices: list[float],
        high_history: list[float] | None = None,
        low_history: list[float] | None = None,
    ) -> tuple[float, float]:
        period = self.stoch_k_period
        d_period = self.stoch_d_period
        if len(prices) < period + d_period:
            return 50.0, 50.0

        if (
            high_history is not None
            and low_history is not None
            and len(high_history) >= len(prices)
            and len(low_history) >= len(prices)
        ):
            stoch_k, stoch_d = TechnicalIndicators.calculate_stochastic_from_prices(
                closes=prices,
                highs=high_history[-len(prices) :],
                lows=low_history[-len(prices) :],
                k_period=period,
                d_period=d_period,
            )
            if stoch_k is not None and stoch_d is not None:
                return float(stoch_k), float(stoch_d)

        k_values = []
        for i in range(d_period):
            idx = len(prices) - d_period + i
            window = prices[idx - period + 1 : idx + 1]
            high = max(window)
            low = min(window)
            k_values.append(50.0 if high == low else (prices[idx] - low) / (high - low) * 100)
        return k_values[-1], sum(k_values) / len(k_values)

    def reset(self) -> None:
        self._prev_stoch_k = None
        self._prev_stoch_d = None
        self._oversold_seen = False
        self._pullback_bars = 0
        self._bars_since_exit = 999999


class MA5BreakoutSignalGenerator(BaseSignalGenerator):
    def __init__(
        self,
        short_ma_period: int = 5,
        long_ma_period: int = 300,
        envelope_percentage: float = 0.7,
        secondary_ma_period: int = 400,
        secondary_envelope_percentage: float = 0.7,
        volume_ma_period: int = 20,
        volume_ratio_threshold: float = 1.0,
        use_volume_filter: bool = True,
    ):
        self.short_ma_period = short_ma_period
        self.long_ma_period = long_ma_period
        self.envelope_percentage = envelope_percentage
        self.secondary_ma_period = secondary_ma_period
        self.secondary_envelope_percentage = secondary_envelope_percentage
        self.volume_ma_period = volume_ma_period
        self.volume_ratio_threshold = volume_ratio_threshold
        self.use_volume_filter = use_volume_filter
        self._prev_ma5_above_upper = False
        self._entry_triggered = False
        self._volume_history: list[float] = []

    @property
    def min_period(self) -> int:
        return max(self.long_ma_period, self.secondary_ma_period, self.volume_ma_period)

    def generate_signal(
        self,
        price_history: list[float],
        current_price: Decimal,
        volume: float | None = None,
        **kwargs: object,
    ) -> str:
        if len(price_history) < self.min_period:
            return "hold"
        if volume is not None:
            self._volume_history.append(volume)
        ma5 = self._calculate_sma(price_history, self.short_ma_period)
        ma300 = self._calculate_sma(price_history, self.long_ma_period)
        upper_300 = ma300 * (1 + self.envelope_percentage / 100)
        ma5_above_upper_300 = ma5 > upper_300
        price_above_upper_300 = float(current_price) > upper_300
        if self._entry_triggered and not ma5_above_upper_300:
            self._entry_triggered = False
            self._prev_ma5_above_upper = False
            return "sell"
        if not self._prev_ma5_above_upper and ma5_above_upper_300:
            if self.use_volume_filter and not self._check_volume_condition():
                self._prev_ma5_above_upper = ma5_above_upper_300
                return "hold"
            if price_above_upper_300:
                self._prev_ma5_above_upper = ma5_above_upper_300
                self._entry_triggered = True
                return "buy"
        self._prev_ma5_above_upper = ma5_above_upper_300
        return "hold"

    def _calculate_sma(self, prices: list[float], period: int) -> float:
        if len(prices) < period:
            return 0.0
        return sum(prices[-period:]) / period

    def _check_volume_condition(self) -> bool:
        if len(self._volume_history) < self.volume_ma_period:
            return True
        avg_volume = sum(self._volume_history[-self.volume_ma_period :]) / self.volume_ma_period
        current_volume = self._volume_history[-1] if self._volume_history else 0
        return current_volume >= avg_volume * self.volume_ratio_threshold

    def reset(self) -> None:
        self._prev_ma5_above_upper = False
        self._entry_triggered = False
        self._volume_history.clear()


def create_signal_generator(strategy_type: str, **kwargs) -> BaseSignalGenerator:
    if strategy_type == "golden_cross":
        return GoldenCrossSignalGenerator(**kwargs)
    if strategy_type == "ma5_breakout":
        return MA5BreakoutSignalGenerator(**kwargs)
    return BollingerEnvelopeSignalGenerator(
        bb_period=kwargs.get("bb_period", 20),
        bb_std_multiplier=kwargs.get("bb_std_multiplier", 2.0),
        env_period=kwargs.get("env_period", 20),
        env_percentage=kwargs.get("env_percentage", 2.0),
        use_strict_mode=kwargs.get("use_strict_mode", True),
    )
