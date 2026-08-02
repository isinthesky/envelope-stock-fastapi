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
    # 2020~2022 레짐 추가(walk-forward 다국면 검증에서 2022 약세장을 비용 반영해
    # 백테스트하기 위함). 한국 유가증권시장 증권거래세(농특세 0.15% 포함) 기준:
    #   2020: 0.25%(거래세 0.10% + 농특세 0.15%)
    #   2021~2022: 0.23%(0.08% + 0.15%)
    # ⚠️ 국내 주식형 ETF는 실제로 증권거래세가 면제되므로 이 세율 적용은 비용을
    #    과대계상(보수적)한다. go/no-go 판단에는 안전한 방향이며, 필요 시
    #    BacktestConfigDTO.use_tax=False 로 종목군에 맞게 끌 수 있다.
    BacktestCostSchedule(
        effective_from=date(2020, 1, 1),
        sell_tax_rate=Decimal("0.0025"),
        default_commission_rate=Decimal("0.00015"),
        default_slippage_rate=Decimal("0.0005"),
        price_tick=_PRICE_TICK_ONE_KRW,
        source_label="krx-securities-transaction-tax:regime-2020-01-01",
    ),
    BacktestCostSchedule(
        effective_from=date(2021, 1, 1),
        sell_tax_rate=Decimal("0.0023"),
        default_commission_rate=Decimal("0.00015"),
        default_slippage_rate=Decimal("0.0005"),
        price_tick=_PRICE_TICK_ONE_KRW,
        source_label="krx-securities-transaction-tax:regime-2021-01-01",
    ),
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
