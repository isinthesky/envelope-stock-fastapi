# -*- coding: utf-8 -*-
"""Canonical golden-cross pullback strategy contract."""

from dataclasses import dataclass
from enum import StrEnum


class GoldenCrossScanState(StrEnum):
    NOT_GC = "NOT_GC"
    GC_ACTIVE = "GC_ACTIVE"
    WAITING_FOR_PULLBACK = "WAITING_FOR_PULLBACK"
    READY_TO_BUY = "READY_TO_BUY"
    BUY_INTEREST = "BUY_INTEREST"
    OPTIMAL_BUY = "OPTIMAL_BUY"
    # [#2/#3] 시장 공포 윈도우 중 개별 과매도로 진입하는 비-GC 후보 (fear-buy)
    FEAR_BUY = "FEAR_BUY"


class GoldenCrossTradeSignal(StrEnum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class GoldenCrossTransitionReason(StrEnum):
    GOLDEN_CROSS_DETECTED = "golden_cross_detected"
    GC_INVALIDATED = "gc_invalidated"
    GC_INVALIDATED_DURING_READY = "gc_invalidated_during_ready"
    PULLBACK_DETECTED = "pullback_detected"
    STOCH_RECOVERY_CROSSOVER = "stoch_recovery_crossover"
    STOCH_STRONG_RECOVERY = "stoch_strong_recovery"
    UNKNOWN_STATE_RESET = "unknown_state_reset"


class GoldenCrossRiskExitReason(StrEnum):
    DEAD_CROSS = "dead_cross"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    TRAILING_STOP = "trailing_stop"
    MAX_HOLD = "max_hold"
    PARTIAL_TAKE_PROFIT_1 = "partial_take_profit_1"
    PARTIAL_TAKE_PROFIT_2 = "partial_take_profit_2"
    BREAKEVEN = "breakeven"


@dataclass(frozen=True, slots=True)
class GoldenCrossPullbackParameters:
    short_period: int = 55
    long_period: int = 165
    stoch_k_period: int = 14
    stoch_d_period: int = 3
    oversold_threshold: float = 30.0
    recovery_threshold: float = 20.0
    strong_recovery_threshold: float = 30.0
    min_ma_gap: float = 0.0
    max_ma_gap: float = 8.0
    min_pullback_bars: int = 2
    min_reentry_cooldown_bars: int = 5


@dataclass(frozen=True, slots=True)
class GoldenCrossScanContext:
    is_gc_active: bool
    stoch_k: float
    stoch_d: float
    stoch_threshold: float
    ma_gap_ratio: float
    prev_stoch_k: float | None = None
    recent_oversold: bool = False
    recovery_threshold: float = 20.0
    strong_recovery_threshold: float = 30.0
    require_momentum_turn: bool = True
    min_ma_gap: float = 0.0
    max_ma_gap: float = 8.0


DEFAULT_GOLDEN_CROSS_PULLBACK = GoldenCrossPullbackParameters()
GOLDEN_CROSS_SCAN_STATE_ORDER: tuple[GoldenCrossScanState, ...] = (
    GoldenCrossScanState.OPTIMAL_BUY,
    GoldenCrossScanState.BUY_INTEREST,
    GoldenCrossScanState.READY_TO_BUY,
    GoldenCrossScanState.WAITING_FOR_PULLBACK,
    GoldenCrossScanState.GC_ACTIVE,
    GoldenCrossScanState.NOT_GC,
)
GOLDEN_CROSS_BUY_CANDIDATE_STATES: tuple[GoldenCrossScanState, ...] = (
    GoldenCrossScanState.OPTIMAL_BUY,
    GoldenCrossScanState.BUY_INTEREST,
    GoldenCrossScanState.READY_TO_BUY,
)


class GoldenCrossStrategyContract:
    @staticmethod
    def is_buy_entry_ready(context: GoldenCrossScanContext) -> bool:
        """Return whether a pullback recovery satisfies the canonical entry rule."""
        return (
            GoldenCrossStrategyContract.classify_scan_state(context)
            == GoldenCrossScanState.OPTIMAL_BUY
        )

    @staticmethod
    def classify_scan_state(context: GoldenCrossScanContext) -> GoldenCrossScanState:
        if not context.is_gc_active:
            return GoldenCrossScanState.NOT_GC

        if context.stoch_k < context.stoch_threshold:
            return GoldenCrossScanState.READY_TO_BUY

        if context.stoch_k >= 50:
            return GoldenCrossScanState.GC_ACTIVE

        is_healthy_trend = context.min_ma_gap <= context.ma_gap_ratio <= context.max_ma_gap
        is_momentum_turning = (
            context.stoch_k > context.stoch_d if context.require_momentum_turn else True
        )
        is_rising = context.prev_stoch_k is None or context.stoch_k > context.prev_stoch_k
        recovered_from_pullback = (
            context.recent_oversold and context.stoch_k >= context.recovery_threshold and is_rising
        )
        strong_recovery = (
            context.recent_oversold
            and context.stoch_k >= context.strong_recovery_threshold
            and is_rising
        )

        if (
            (recovered_from_pullback or strong_recovery)
            and is_momentum_turning
            and is_healthy_trend
        ):
            return GoldenCrossScanState.OPTIMAL_BUY

        if context.recent_oversold and is_healthy_trend and (is_rising or is_momentum_turning):
            return GoldenCrossScanState.BUY_INTEREST

        return GoldenCrossScanState.WAITING_FOR_PULLBACK

    @staticmethod
    def buy_candidate_state_values() -> list[str]:
        return [state.value for state in GOLDEN_CROSS_BUY_CANDIDATE_STATES]
