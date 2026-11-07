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


# ==================== 매도 증권거래세(농특세 포함) 스케줄 ====================
# 편집 포인트: 아래 표(_SELL_TAX_TABLE)만 고치면 된다. 세율은 KRX 유가증권/코스닥
# 상장 **주식** 매도 시 합계(증권거래세 + 농어촌특별세, KOSPI 농특세 0.15%)다.
#
#   effective_from | 합계세율 | 근거/확신
#   2018-01-01     | 0.30%   | 거래세 0.15% + 농특세 0.15% (2019-06-02까지) — 홀드아웃(2018~19)용
#   2019-06-03     | 0.25%   | 거래세 0.10% + 농특세 0.15% (2019-06-03 인하)
#   2020-01-01     | 0.25%   | 거래세 0.10% + 농특세 0.15%
#   2021-01-01     | 0.23%   | 0.08% + 0.15% (2021~2022)
#   2023-01-01     | 0.20%   | 0.05% + 0.15%
#   2024-01-01     | 0.18%   | 0.03% + 0.15%
#   2025-01-01     | 0.15%   | 0.00% + 0.15%
#   2026-01-01     | 0.20%   | ⚠️ 2025 세법개정으로 0.05% 환원(0.05%+0.15%)으로 파악 — 약 80% 확신.
#                              시행령 최종 확정치로 재확인 후 필요 시 이 행만 수정할 것.
#
# ⚠️ 국내 상장 ETF(수익증권)는 증권거래세 **면제** → `order_manager`가 ETF 심볼에
#    0%를 적용한다(`etf_tax_exempt`). 참고(미구현): 국내주식형 외 ETF(해외/채권/
#    원자재 등)는 매매차익에 배당소득세 15.4%가 과세된다 — 이 엔진은 반영하지 않는다.
_SELL_TAX_TABLE: Final[tuple[tuple[date, str, str], ...]] = (
    (date(2018, 1, 1), "0.0030", "krx-securities-transaction-tax:regime-2018-01-01"),
    (date(2019, 6, 3), "0.0025", "krx-securities-transaction-tax:regime-2019-06-03"),
    (date(2020, 1, 1), "0.0025", "krx-securities-transaction-tax:regime-2020-01-01"),
    (date(2021, 1, 1), "0.0023", "krx-securities-transaction-tax:regime-2021-01-01"),
    (date(2023, 1, 1), "0.0020", "krx-securities-transaction-tax:regime-2023-01-01"),
    (date(2024, 1, 1), "0.0018", "krx-securities-transaction-tax:regime-2024-01-01"),
    (date(2025, 1, 1), "0.0015", "krx-securities-transaction-tax:regime-2025-01-01"),
    (
        date(2026, 1, 1),
        "0.0020",
        "krx-securities-transaction-tax:regime-2026-01-01(unconfirmed~80%)",
    ),
)
_DEFAULT_COMMISSION_RATE: Final = Decimal("0.00015")
_DEFAULT_SLIPPAGE_RATE: Final = Decimal("0.0005")

_COST_SCHEDULES: Final[tuple[BacktestCostSchedule, ...]] = tuple(
    BacktestCostSchedule(
        effective_from=effective_from,
        sell_tax_rate=Decimal(rate),
        default_commission_rate=_DEFAULT_COMMISSION_RATE,
        default_slippage_rate=_DEFAULT_SLIPPAGE_RATE,
        price_tick=_PRICE_TICK_ONE_KRW,
        source_label=label,
    )
    for effective_from, rate, label in _SELL_TAX_TABLE
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
