# -*- coding: utf-8 -*-
"""GoldenCrossSignalGenerator - 스윙형 골든크로스 백테스트 시그널 생성기."""

from decimal import Decimal

from src.application.common.indicators import TechnicalIndicators
from src.application.domain.backtest.generators.base import BaseSignalGenerator
from src.application.domain.strategy.strategy_contract import (
    DEFAULT_GOLDEN_CROSS_PULLBACK,
    GoldenCrossTradeSignal,
)


class GoldenCrossSignalGenerator(BaseSignalGenerator):
    """스윙형 골든크로스 시그널 생성기.

    ⚠️ 검증(walk-forward) 부적합: 이 생성기의 매수 판정(`_should_buy`)은 실주문
    경로(`state_machine` + canonical `GoldenCrossStrategyContract`)와 **다르게**
    독자 재구현되어 있다(예: level-GC vs crossover, recovery 30 vs 25 config,
    pullback_bars/cooldown, `<50`·MA gap 게이트 부재). 따라서 이 경로로 얻은
    백테스트 결과는 "실제 매매되는 로직"을 대표하지 않는다.

    라이브와 동일한 시그널로 검증하려면
    `backtest.golden_cross_parity.GoldenCrossParityReplay` 를 사용하라.
    이 생성기는 온디맨드 백테스트(단일런)의 진단/호환 용도로만 유지한다.
    """

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
