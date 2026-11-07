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

    # 2026 환원 세율(0.05%+농특세 0.15%) — 약 80% 확신, cost_schedule 표 주석 참고
    assert schedule.sell_tax_rate == Decimal("0.0020")
    assert schedule.default_commission_rate == Decimal("0.00015")
    assert schedule.default_slippage_rate == Decimal("0.0005")
    assert schedule.source_label.startswith("krx-securities-transaction-tax:regime-2026-01-01")


@pytest.mark.parametrize(
    ("trade_date", "rate"),
    [
        (date(2022, 12, 30), "0.0023"),
        (date(2023, 6, 1), "0.0020"),
        (date(2024, 12, 31), "0.0018"),
        (date(2025, 1, 2), "0.0015"),
        (date(2025, 12, 31), "0.0015"),
        (date(2026, 1, 2), "0.0020"),
    ],
)
def test_krx_sell_tax_schedule_by_year(trade_date: date, rate: str) -> None:
    assert get_backtest_cost_schedule(trade_date).sell_tax_rate == Decimal(rate)


def test_get_latest_backtest_cost_schedule_returns_latest_declared_regime() -> None:
    schedule = get_latest_backtest_cost_schedule()

    assert schedule.effective_from == date(2026, 1, 1)
    assert schedule.sell_tax_rate == Decimal("0.0020")


def test_get_backtest_cost_schedule_supports_2022_bear_regime() -> None:
    schedule = get_backtest_cost_schedule(date(2022, 6, 15))

    assert schedule.sell_tax_rate == Decimal("0.0023")
    assert schedule.source_label == "krx-securities-transaction-tax:regime-2021-01-01"


def test_get_backtest_cost_schedule_supports_2020_regime() -> None:
    schedule = get_backtest_cost_schedule(date(2020, 3, 20))  # 코로나 급락 구간

    assert schedule.sell_tax_rate == Decimal("0.0025")
    assert schedule.source_label == "krx-securities-transaction-tax:regime-2020-01-01"


def test_get_backtest_cost_schedule_rejects_unsupported_date() -> None:
    with pytest.raises(UnsupportedBacktestCostDateError, match="1900-01-01"):
        get_backtest_cost_schedule(date(1900, 1, 1))
