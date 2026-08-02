# -*- coding: utf-8 -*-
"""MA5BreakoutSignalGenerator - MA5/MA300 엔벨로프 돌파 백테스트 시그널 생성기."""

from decimal import Decimal

from src.application.domain.backtest.generators.base import BaseSignalGenerator


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
