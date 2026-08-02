# -*- coding: utf-8 -*-
"""Walk-Forward Runner + Window Scheduler 테스트 (P3)."""

from datetime import date
from decimal import Decimal

import numpy as np
import pandas as pd

from src.application.domain.backtest.dto import BacktestConfigDTO
from src.application.domain.backtest.portfolio_parity_engine import PortfolioConstraints
from src.application.domain.backtest.walk_forward_runner import (
    WalkForwardCandidate,
    WalkForwardRunner,
)
from src.application.domain.backtest.walk_forward_windows import (
    WalkForwardWindow,
    generate_rolling_windows,
)
from src.application.domain.strategy.dto import (
    GoldenCrossConfigDTO,
    GoldenCrossMAConfig,
    StochasticConfig,
)

CAPITAL = BacktestConfigDTO(initial_capital=Decimal("10000000"))


def _cfg(oversold: float) -> GoldenCrossConfigDTO:
    return GoldenCrossConfigDTO(
        ma_config=GoldenCrossMAConfig(short_period=5, long_period=60),
        stochastic_config=StochasticConfig(oversold_threshold=oversold),
    )


def _walk_panel(seed: int, n: int = 520, start: str = "2021-01-04") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    steps = rng.normal(0.0006, 0.02, n)
    closes = 100.0 * np.exp(np.cumsum(steps))
    dates = pd.date_range(start, periods=n, freq="B")
    close = np.asarray(closes, dtype=float)
    openp = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(openp, close) * 1.004
    low = np.minimum(openp, close) * 0.996
    return pd.DataFrame(
        {
            "timestamp": dates,
            "open": openp,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 100_000),
        }
    )


# ==================== Window scheduler ====================


def test_generate_rolling_windows_shapes_and_embargo():
    days = [date(2021, 1, 1) + pd.Timedelta(days=i) for i in range(0)]  # placeholder
    days = list(pd.date_range("2021-01-04", periods=400, freq="B").date)
    windows = generate_rolling_windows(days, train_size=120, test_size=40, step=40, embargo=5)
    assert len(windows) >= 2
    for w in windows:
        assert isinstance(w, WalkForwardWindow)
        assert w.train_end < w.test_start  # embargo gap 보장
        ti = days.index(w.train_end)
        si = days.index(w.test_start)
        assert si - ti == 6  # 1 + embargo(5)


def test_windows_reject_bad_params():
    days = list(pd.date_range("2021-01-04", periods=100, freq="B").date)
    try:
        generate_rolling_windows(days, train_size=0, test_size=10, step=10)
    except ValueError:
        return
    raise AssertionError("expected ValueError for train_size=0")


# ==================== Runner end-to-end ====================


def _panels(symbols):
    return {s: _walk_panel(seed=i) for i, s in enumerate(symbols)}


def _trading_days(panels):
    all_d = set()
    for df in panels.values():
        all_d.update(ts.date() for ts in df["timestamp"])
    return sorted(all_d)


def test_runner_produces_real_oos_metrics_and_frozen_hashes():
    panels = _panels(["A", "B", "C", "D"])
    days = _trading_days(panels)
    windows = generate_rolling_windows(days, train_size=140, test_size=40, step=40, embargo=5)
    assert len(windows) >= 2

    runner = WalkForwardRunner(
        candidates=[
            WalkForwardCandidate("os25", _cfg(25.0)),
            WalkForwardCandidate("os30", _cfg(30.0)),
        ],
        constraints=PortfolioConstraints(max_positions=3),
        backtest_config=CAPITAL,
        selection_metric="sharpe_ratio",
    )
    report = runner.run(panels, days, windows)

    assert len(report.folds) == len(windows)
    assert report.candidates == 2
    # 모든 심볼이 전기간 보유 → 모든 fold eligible → trials = 2 × folds
    assert report.trials == 2 * len(windows)

    # OOS 집계 지표 존재
    for k in ("cagr", "sharpe", "mdd", "total_return", "trading_days", "folds"):
        assert k in report.oos
    assert isinstance(report.oos["sharpe"], float)

    # 각 fold: 선택 라벨 + 16-hex freeze 해시
    for f in report.folds:
        assert f.selected_label in {"os25", "os30"}
        assert len(f.selected_hash) == 16
        assert "sharpe" in f.test  # OOS 지표 계산됨

    assert "Walk-Forward" in report.markdown
    assert "Stitched OOS" in report.markdown

    # P4 과적합 통계 배선 확인
    assert "deflated_sharpe" in report.stats
    assert "pbo" in report.stats  # 후보 2개 → PBO 산출됨(None 아님)
    assert report.stats["pbo"] is not None
    assert 0.0 <= report.stats["deflated_sharpe"] <= 1.0
    assert isinstance(report.oos_daily_returns, list)
    assert "과적합 정량화" in report.markdown


def test_runner_asof_universe_excludes_short_history_symbol():
    # A,B,C 전기간 / SHORT는 후반부만 존재 → 초기 fold에서 제외되어야 함
    panels = _panels(["A", "B", "C"])
    short = _walk_panel(seed=99)
    # 초기 fold의 워밍업 lookback은 못 맞추고 후기 fold는 맞추는 시작점
    short = short.iloc[100:].reset_index(drop=True)
    panels["SHORT"] = short
    days = _trading_days(panels)
    windows = generate_rolling_windows(days, train_size=140, test_size=40, step=40, embargo=5)

    runner = WalkForwardRunner(
        candidates=[WalkForwardCandidate("os25", _cfg(25.0))],
        constraints=PortfolioConstraints(max_positions=3),
        backtest_config=CAPITAL,
    )
    report = runner.run(panels, days, windows)

    # 첫 fold는 SHORT 제외(3종목), 마지막 fold는 SHORT 포함(4종목)
    first = report.folds[0]
    last = report.folds[-1]
    assert first.eligible_symbols == 3
    assert last.eligible_symbols == 4


def test_stitch_oos_dedups_overlapping_test_windows():
    # 겹치는 test 창(step<test_size)이 같은 거래일을 이중계산하지 않아야 함
    from datetime import datetime

    from src.application.domain.backtest.dto import DailyStatsDTO

    def _ds(day: int, equity: str) -> DailyStatsDTO:
        return DailyStatsDTO(
            date=datetime(2023, 1, day),
            equity=Decimal(equity),
            cash=Decimal(equity),
            position_value=Decimal("0"),
            daily_return=0.0,
            cumulative_return=0.0,
            drawdown=0.0,
        )

    seg1 = [_ds(2, "10000000"), _ds(3, "10100000"), _ds(4, "10200000")]
    seg2 = [_ds(4, "10000000"), _ds(5, "10300000"), _ds(6, "10500000")]  # 1/4 겹침

    runner = WalkForwardRunner(candidates=[WalkForwardCandidate("os25", _cfg(25.0))])
    oos, oos_returns = runner._stitch_oos([seg1, seg2], Decimal("10000000"))

    # 고유 거래일 5개(1/2~1/6), 겹친 1/4는 한 번만
    assert oos["trading_days"] == 5
    assert oos["folds"] == 2
    assert len(oos_returns) == 5  # 반환된 OOS 일별수익도 dedup됨


def test_runner_requires_candidates_and_inputs():
    try:
        WalkForwardRunner(candidates=[])
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for empty candidates")

    runner = WalkForwardRunner(candidates=[WalkForwardCandidate("os25", _cfg(25.0))])
    try:
        runner.run({}, [], [])
    except ValueError:
        return
    raise AssertionError("expected ValueError for empty panels/windows")
