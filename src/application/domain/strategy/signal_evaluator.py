# -*- coding: utf-8 -*-
"""Shared signal evaluation helpers for strategy recommendations."""

from dataclasses import dataclass


@dataclass(frozen=True)
class GoldenCrossScanContext:
    """Inputs required to classify a golden-cross scan result."""

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


class GoldenCrossSignalEvaluator:
    """Classifies buy-candidate states using the same pullback/recovery flow."""

    @staticmethod
    def classify_scan_state(context: GoldenCrossScanContext) -> str:
        if not context.is_gc_active:
            return "NOT_GC"

        if context.stoch_k < context.stoch_threshold:
            return "READY_TO_BUY"

        if context.stoch_k >= 50:
            return "GC_ACTIVE"

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
            return "OPTIMAL_BUY"

        if context.recent_oversold and is_healthy_trend and (is_rising or is_momentum_turning):
            return "BUY_INTEREST"

        return "WAITING_FOR_PULLBACK"
