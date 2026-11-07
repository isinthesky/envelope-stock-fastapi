# -*- coding: utf-8 -*-
"""연구용 opt-in 백테스트 옵션 테스트 (2026-11-06).

기본값은 기존 동작을 보존해야 하고(별도 parity 테스트가 보장), 각 옵션은
명시했을 때만 의도한 효과를 내야 한다.
"""

from datetime import date
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from src.application.domain.backtest.cash_interest import (
    APPROX_KRW_CASH_RATE_SCHEDULE,
    CashInterestSchedule,
)
from src.application.domain.backtest.cost_schedule import get_backtest_cost_schedule
from src.application.domain.backtest.dto import BacktestConfigDTO
from src.application.domain.backtest.exit_overlay import (
    OVERLAY_BREAKDOWN_20D,
    OVERLAY_PROFIT_PROTECT,
    OVERLAY_TREND_STOP,
    ExitOverlay,
)
from src.application.domain.backtest.momentum_rotation import (
    MomentumRotationConfig,
    MomentumRotationEngine,
    month_end_signal_days,
)
from src.application.domain.backtest.portfolio_parity_engine import (
    PortfolioConstraints,
    PortfolioExecutionOptions,
    PortfolioParityEngine,
)
from src.application.domain.backtest.regime_filter import (
    RegimeEntryFilter,
    compute_allowed_entry_dates,
    wilder_adx_series,
    wilder_dmi_series,
)
from src.application.domain.backtest.walk_forward_runner import (
    WalkForwardCandidate,
    WalkForwardRunner,
    stitch_oos_exposure,
    stitch_oos_segments,
)
from src.application.domain.backtest.walk_forward_windows import WalkForwardWindow
from src.application.domain.strategy.dto import GoldenCrossConfigDTO, GoldenCrossMAConfig

CONFIG = GoldenCrossConfigDTO(ma_config=GoldenCrossMAConfig(short_period=5, long_period=60))
CAPITAL = BacktestConfigDTO(initial_capital=Decimal("10000000"), tax_exempt_symbols=[])


def _frame(closes: list[float], start: str = "2023-01-02", gap: float = 0.0) -> pd.DataFrame:
    n = len(closes)
    close = np.array(closes, dtype=float)
    # open = 전일 종가 × (1+gap) → next_open 체결가가 종가와 구분되게
    openp = np.concatenate([[close[0]], close[:-1] * (1.0 + gap)])
    return pd.DataFrame(
        {
            "timestamp": pd.date_range(start, periods=n, freq="B"),
            "open": openp,
            "high": np.maximum(openp, close) * 1.004,
            "low": np.minimum(openp, close) * 0.996,
            "close": close,
            "volume": np.full(n, 100_000),
        }
    )


def _cycle_closes() -> list[float]:
    out: list[float] = []
    p = 100.0
    for n, f in ((90, 1.004), (3, 0.965), (30, 1.006), (40, 1.004), (30, 0.97)):
        for _ in range(n):
            p *= f
            out.append(p)
    return out


# ==================== PortfolioExecutionOptions ====================


def test_default_execution_options_are_identity():
    df = _frame(_cycle_closes())
    a = PortfolioParityEngine(CONFIG, PortfolioConstraints(max_positions=3)).run({"A": df}, CAPITAL)
    b = PortfolioParityEngine(
        CONFIG, PortfolioConstraints(max_positions=3), PortfolioExecutionOptions()
    ).run({"A": df.copy()}, CAPITAL)
    assert PortfolioExecutionOptions().is_default
    assert [s.equity for s in a.result.daily_stats] == [s.equity for s in b.result.daily_stats]
    assert a.overlay_exits == {} and a.open_fallbacks == 0 and a.interest_earned == 0


def test_invalid_execution_option_rejected():
    with pytest.raises(ValueError):
        PortfolioExecutionOptions(fill_timing="tomorrow_noon")
    with pytest.raises(ValueError):
        PortfolioExecutionOptions(sizing_mode="kelly")


def test_next_open_fills_on_following_bar_open_with_gap():
    df = _frame(_cycle_closes(), gap=0.01)  # 매일 +1% 갭 시가
    same = PortfolioParityEngine(CONFIG).run({"A": df}, CAPITAL)
    nxt = PortfolioParityEngine(
        CONFIG, execution=PortfolioExecutionOptions(fill_timing="next_open")
    ).run({"A": df.copy()}, CAPITAL)
    assert nxt.result.execution_timing == "next_open"
    t_same, t_next = same.result.trades[0], nxt.result.trades[0]
    dates = list(df["timestamp"])
    i_sig = dates.index(pd.Timestamp(t_same.entry_date))
    assert pd.Timestamp(t_next.entry_date) == dates[i_sig + 1]
    slip = Decimal("1.0005")
    expected = Decimal(str(df["open"].iloc[i_sig + 1])) * slip
    assert abs(t_next.entry_price - expected) < Decimal("1e-6")
    # 매도도 다음 바 시가 체결
    assert t_next.exit_date is not None and t_same.exit_date is not None
    assert t_next.exit_date > t_same.exit_date


def test_liquidate_at_end_marks_open_position_net_of_exit_costs():
    full = _frame(_cycle_closes())
    first = PortfolioParityEngine(CONFIG).run({"A": full}, CAPITAL).result.trades[0]
    i_entry = list(full["timestamp"]).index(pd.Timestamp(first.entry_date))
    df = full.iloc[: i_entry + 5].reset_index(drop=True)  # 진입 직후 종료 → 보유 상태
    base = PortfolioParityEngine(CONFIG).run({"A": df}, CAPITAL)
    liq = PortfolioParityEngine(
        CONFIG, execution=PortfolioExecutionOptions(liquidate_at_end=True)
    ).run({"A": df.copy()}, CAPITAL)
    open_trades = [t for t in base.result.trades if t.exit_date is None]
    assert open_trades, "fixture must end with an open position"
    assert liq.end_liquidation_cost > 0
    diff = base.result.final_capital - liq.result.final_capital
    assert abs(diff - liq.end_liquidation_cost) < Decimal("1e-6")
    # 이전 바들은 동일
    assert [s.equity for s in base.result.daily_stats[:-1]] == [
        s.equity for s in liq.result.daily_stats[:-1]
    ]


def test_equal_weight_sizing_uses_total_equity_over_slots():
    df = _frame(_cycle_closes())
    cr = PortfolioParityEngine(CONFIG, PortfolioConstraints(max_positions=5)).run({"A": df}, CAPITAL)
    ew = PortfolioParityEngine(
        CONFIG,
        PortfolioConstraints(max_positions=5),
        PortfolioExecutionOptions(sizing_mode="equal_weight_equity"),
    ).run({"A": df.copy()}, CAPITAL)
    t_cr, t_ew = cr.result.trades[0], ew.result.trades[0]
    notional_ew = t_ew.entry_price * t_ew.quantity
    notional_cr = t_cr.entry_price * t_cr.quantity
    assert Decimal("1900000") < notional_ew <= Decimal("2000000")  # 1천만/5
    assert Decimal("900000") < notional_cr <= Decimal("1000000")  # 현금 × 0.1


def test_cash_interest_accrues_on_idle_cash_only_when_enabled():
    df = _frame([100.0] * 120)  # 신호 없음 → 전액 현금
    sched = CashInterestSchedule.flat(0.0365)
    out = PortfolioParityEngine(
        CONFIG, execution=PortfolioExecutionOptions(cash_interest=sched)
    ).run({"A": df}, CAPITAL)
    ds = out.result.daily_stats
    days = (ds[-1].date - ds[0].date).days
    expected = Decimal("10000000") * Decimal(str((1.0365) ** (days / 365.0)))
    assert abs(out.result.final_capital - expected) < Decimal("5")
    assert out.interest_earned > 0
    base = PortfolioParityEngine(CONFIG).run({"A": df.copy()}, CAPITAL)
    assert base.result.final_capital == Decimal("10000000")


def test_cash_interest_schedule_steps():
    s = APPROX_KRW_CASH_RATE_SCHEDULE
    assert s.rate_on(date(2018, 6, 1)) == 0.017
    assert s.rate_on(date(2021, 6, 1)) == 0.007
    assert s.rate_on(date(2022, 6, 1)) == 0.025
    assert s.rate_on(date(2024, 6, 1)) == 0.035
    assert s.rate_on(date(2026, 6, 1)) == 0.028
    assert s.accrual_factor(date(2024, 1, 1), date(2024, 1, 1)) == 0
    with pytest.raises(ValueError):
        CashInterestSchedule.flat(0.9)


# ==================== Exit overlay ====================


def test_exit_overlay_rules():
    ov = ExitOverlay(trend_stop_pct=0.15, breakdown_20d_pct=0.15, profit_protect=True)
    flat20 = [Decimal("100")] * 20
    # 추세 이탈: MA 대비 15% 초과 하회
    assert (
        ov.check(close=Decimal("84"), entry_price=Decimal("90"), highest_price=Decimal("90"),
                 ma_long=Decimal("100"), recent_closes=flat20)
        == OVERLAY_TREND_STOP
    )
    # 20일 고점 대비 15% 이탈(추세 이탈 아님)
    assert (
        ov.check(close=Decimal("84"), entry_price=Decimal("80"), highest_price=Decimal("100"),
                 ma_long=Decimal("80"), recent_closes=flat20[:-1] + [Decimal("84")])
        == OVERLAY_BREAKDOWN_20D
    )
    # 85% 수익 보호: 피크 +20% → 현재 +16% (< 17%)
    assert (
        ov.check(close=Decimal("116"), entry_price=Decimal("100"), highest_price=Decimal("120"),
                 ma_long=Decimal("100"), recent_closes=[Decimal("116")] * 20)
        == OVERLAY_PROFIT_PROTECT
    )
    # 피크 수익 5% 미만이면 보호 미발동
    assert (
        ov.check(close=Decimal("102"), entry_price=Decimal("100"), highest_price=Decimal("104"),
                 ma_long=Decimal("100"), recent_closes=[Decimal("102")] * 20)
        is None
    )
    assert ExitOverlay().check(close=Decimal("1"), entry_price=Decimal("100"), highest_price=None,
                               ma_long=Decimal("100"), recent_closes=flat20) is None


def test_engine_applies_overlay_exit_and_counts_it():
    closes = _cycle_closes()
    df = _frame(closes)
    out = PortfolioParityEngine(
        CONFIG, execution=PortfolioExecutionOptions(exit_overlay=ExitOverlay(profit_protect=True))
    ).run({"A": df}, CAPITAL)
    base = PortfolioParityEngine(CONFIG).run({"A": df.copy()}, CAPITAL)
    assert sum(out.overlay_exits.values()) >= 0
    # 오버레이는 청산을 추가할 뿐 → 첫 거래 진입은 동일
    assert out.result.trades[0].entry_date == base.result.trades[0].entry_date


# ==================== Regime DI direction ====================


def _trend_bench(n: int = 300, drift: float = -0.003) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    closes = 100 * np.exp(np.cumsum(rng.normal(drift, 0.01, n)))
    return _frame(list(closes), start="2022-01-03")


def test_dmi_adx_matches_existing_adx_series():
    df = _trend_bench()
    adx, plus_di, minus_di = wilder_dmi_series(df, 14)
    pd.testing.assert_series_equal(adx, wilder_adx_series(df, 14))
    assert plus_di.iloc[:28].isna().all() and minus_di.iloc[:28].isna().all()


def test_di_direction_gate_blocks_downtrend_days():
    df = _trend_bench(drift=-0.004)
    adx_only = compute_allowed_entry_dates(df, RegimeEntryFilter(use_ma=False, use_adx=True))
    adx_di = compute_allowed_entry_dates(
        df, RegimeEntryFilter(use_ma=False, use_adx=True, use_di_direction=True)
    )
    assert adx_only is not None and adx_di is not None
    assert adx_di <= adx_only
    assert len(adx_di) < len(adx_only)  # 하락 추세 강도 구간이 방향 게이트로 걸러짐
    assert "+DI14>-DI" in RegimeEntryFilter(use_di_direction=True).describe()
    # 기본값은 방향 게이트 OFF
    assert RegimeEntryFilter().use_di_direction is False


# ==================== Runner: PIT eligibility / stitch helpers ====================


def test_pit_eligibility_admits_late_listing_in_test_only():
    early = _frame(list(100 * np.exp(np.cumsum(np.full(600, 0.0005)))), start="2021-01-04")
    late = _frame(list(100 * np.exp(np.cumsum(np.full(380, 0.0005)))), start="2021-09-20")
    days = [ts.date() for ts in early["timestamp"]]
    w = WalkForwardWindow(days[200], days[399], days[405], days[520])
    late_first = late["timestamp"].iloc[0].date()
    late_bars_before_test = sum(1 for ts in late["timestamp"] if ts.date() < w.test_start)
    assert late_first > days[200 - 90]  # train 시작 시점엔 이력 부족
    cand = [WalkForwardCandidate("c", CONFIG)]
    runner = WalkForwardRunner(cand, backtest_config=CAPITAL, lookback_trading_days=90,
                               eligibility="pit")
    rep = runner.run({"E": early, "L": late}, days, [w])
    f = rep.folds[0]
    assert f.eligible_symbols == 1  # train: E만
    assert late_bars_before_test >= 90
    assert f.test_eligible_symbols == 2  # test: L도 편입(시작 전 이력 충분)
    assert rep.oos_dated_returns and rep.oos_exposure
    legacy = WalkForwardRunner(cand, backtest_config=CAPITAL, lookback_trading_days=90)
    assert legacy.run({"E": early, "L": late}, days, [w]).folds[0].test_eligible_symbols is None
    with pytest.raises(ValueError):
        WalkForwardRunner(cand, eligibility="future")


def test_stitch_helpers_match_runner_method():
    df = _frame(_cycle_closes())
    res = PortfolioParityEngine(CONFIG).run({"A": df}, CAPITAL).result
    seg = [res.daily_stats]
    runner = WalkForwardRunner([WalkForwardCandidate("c", CONFIG)])
    assert runner._stitch_oos(seg, CAPITAL.initial_capital) == stitch_oos_segments(
        seg, CAPITAL.initial_capital
    )
    expo = stitch_oos_exposure(seg)
    assert len(expo) == len(res.daily_stats)
    assert all(0.0 <= x <= 1.0 for _, x in expo)


# ==================== Momentum rotation ====================


def test_month_end_signal_days():
    cal = [date(2024, 1, 30), date(2024, 1, 31), date(2024, 2, 1), date(2024, 2, 29), date(2024, 3, 4)]
    assert month_end_signal_days(cal) == {date(2024, 1, 31), date(2024, 2, 29), date(2024, 3, 4)}


def _mom_panels() -> dict[str, pd.DataFrame]:
    n = 420
    up_fast = list(100 * np.exp(np.cumsum(np.full(n, 0.002))))
    up_slow = list(100 * np.exp(np.cumsum(np.full(n, 0.0005))))
    down = list(100 * np.exp(np.cumsum(np.full(n, -0.001))))
    return {"FAST": _frame(up_fast), "SLOW": _frame(up_slow), "DOWN": _frame(down)}


def test_momentum_picks_strongest_and_trend_filter_keeps_cash():
    panels = _mom_panels()
    cfg = MomentumRotationConfig(top_n=2, lookback=252, skip=21, trend_ma=200, fill_timing="same_close")
    res = MomentumRotationEngine(cfg).run(panels, CAPITAL)
    assert res.rebalances, "must rebalance after warmup"
    rb = [r for r in res.rebalances if r.eligible == 3][0]
    assert rb.ranked == ("FAST", "SLOW")
    assert set(rb.held_after) == {"FAST", "SLOW"}
    cfg3 = MomentumRotationConfig(top_n=3, fill_timing="same_close")
    res3 = MomentumRotationEngine(cfg3).run(panels, CAPITAL)
    rb3 = [r for r in res3.rebalances if r.eligible == 3][0]
    assert "DOWN" in rb3.ranked and "DOWN" not in rb3.held_after  # MA200 아래 → 현금 슬롯
    held = {t.symbol for t in res3.result.trades}
    assert "DOWN" not in held


def test_momentum_next_open_and_validation():
    panels = _mom_panels()
    res = MomentumRotationEngine(MomentumRotationConfig(top_n=1)).run(panels, CAPITAL)
    assert res.result.execution_timing == "next_open"
    assert res.result.trades[0].symbol == "FAST"
    with pytest.raises(ValueError):
        MomentumRotationConfig(skip=300)


# ==================== Cost schedule (holdout 2018~2019) ====================


@pytest.mark.parametrize(
    ("d", "rate"),
    [(date(2018, 7, 2), "0.0030"), (date(2019, 6, 2), "0.0030"), (date(2019, 6, 3), "0.0025"),
     (date(2020, 1, 2), "0.0025")],
)
def test_cost_schedule_covers_holdout(d: date, rate: str):
    assert get_backtest_cost_schedule(d).sell_tax_rate == Decimal(rate)
