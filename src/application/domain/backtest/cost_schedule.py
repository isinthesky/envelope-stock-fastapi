from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

_PRICE_TICK_ONE_KRW: Final = Decimal("1")


@dataclass(frozen=True, slots=True)
class BacktestCostSchedule:
    effective_from: date
    sell_tax_rate: Decimal
    default_commission_rate: Decimal
    default_slippage_rate: Decimal
    price_tick: Decimal
    source_label: str

    def round_price(self, price: Decimal) -> Decimal:
        return price.quantize(self.price_tick, rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class UnsupportedBacktestCostDateError(Exception):
    requested_date: date
    earliest_supported_date: date

    def __str__(self) -> str:
        return (
            f"unsupported backtest cost schedule date {self.requested_date}; "
            f"earliest supported date is {self.earliest_supported_date}"
        )


_COST_SCHEDULES: Final[tuple[BacktestCostSchedule, ...]] = (
    BacktestCostSchedule(
        effective_from=date(2023, 1, 1),
        sell_tax_rate=Decimal("0.0023"),
        default_commission_rate=Decimal("0.00015"),
        default_slippage_rate=Decimal("0.0005"),
        price_tick=_PRICE_TICK_ONE_KRW,
        source_label="project-plan-claim-ledger:backtest-cost-regime-2023-01-01",
    ),
    BacktestCostSchedule(
        effective_from=date(2025, 1, 1),
        sell_tax_rate=Decimal("0.0018"),
        default_commission_rate=Decimal("0.00015"),
        default_slippage_rate=Decimal("0.0005"),
        price_tick=_PRICE_TICK_ONE_KRW,
        source_label="project-plan-claim-ledger:backtest-cost-regime-2025-01-01",
    ),
)


def get_backtest_cost_schedule(trade_date: date) -> BacktestCostSchedule:
    selected_schedule: BacktestCostSchedule | None = None
    for schedule in _COST_SCHEDULES:
        if schedule.effective_from <= trade_date:
            selected_schedule = schedule

    if selected_schedule is None:
        raise UnsupportedBacktestCostDateError(
            requested_date=trade_date,
            earliest_supported_date=_COST_SCHEDULES[0].effective_from,
        )

    return selected_schedule


def get_latest_backtest_cost_schedule() -> BacktestCostSchedule:
    return _COST_SCHEDULES[-1]
