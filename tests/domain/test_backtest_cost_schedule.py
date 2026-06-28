from datetime import date
from decimal import Decimal

import pytest

from src.application.domain.backtest.cost_schedule import (
    UnsupportedBacktestCostDateError,
    get_backtest_cost_schedule,
    get_latest_backtest_cost_schedule,
)


def test_get_backtest_cost_schedule_returns_labeled_dated_regime() -> None:
    schedule = get_backtest_cost_schedule(date(2026, 6, 28))

    assert schedule.sell_tax_rate == Decimal("0.0018")
    assert schedule.default_commission_rate == Decimal("0.00015")
    assert schedule.default_slippage_rate == Decimal("0.0005")
    assert schedule.source_label == "project-plan-claim-ledger:backtest-cost-regime-2025-01-01"


def test_get_backtest_cost_schedule_supports_prior_tax_regime() -> None:
    schedule = get_backtest_cost_schedule(date(2024, 12, 31))

    assert schedule.sell_tax_rate == Decimal("0.0023")
    assert schedule.source_label == "project-plan-claim-ledger:backtest-cost-regime-2023-01-01"


def test_get_latest_backtest_cost_schedule_returns_latest_declared_regime() -> None:
    schedule = get_latest_backtest_cost_schedule()

    assert schedule.effective_from == date(2025, 1, 1)
    assert schedule.sell_tax_rate == Decimal("0.0018")


def test_get_backtest_cost_schedule_rejects_unsupported_date() -> None:
    with pytest.raises(UnsupportedBacktestCostDateError, match="1900-01-01"):
        get_backtest_cost_schedule(date(1900, 1, 1))
