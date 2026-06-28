# -*- coding: utf-8 -*-
"""Shared signal evaluation helpers for strategy recommendations."""

from src.application.domain.strategy.strategy_contract import (
    GoldenCrossScanContext,
    GoldenCrossStrategyContract,
)


class GoldenCrossSignalEvaluator:
    """Classifies buy-candidate states using the same pullback/recovery flow."""

    @staticmethod
    def classify_scan_state(context: GoldenCrossScanContext) -> str:
        return GoldenCrossStrategyContract.classify_scan_state(context).value
