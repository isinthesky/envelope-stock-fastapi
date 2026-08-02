# -*- coding: utf-8 -*-
"""엔진/러너 진입 국면 게이트(entry_allowed_dates) 통합 테스트."""

from decimal import Decimal

import numpy as np
import pandas as pd

from src.application.domain.backtest.dto import BacktestConfigDTO
from src.application.domain.backtest.portfolio_parity_engine import (
    PortfolioConstraints,
    PortfolioParityEngine,
)
from src.application.domain.backtest.regime_filter import RegimeEntryFilter
from src.application.domain.backtest.walk_forward_runner import (
    WalkForwardCandidate,
    WalkForwardRunner,
)
from src.application.domain.strategy.dto import GoldenCrossConfigDTO, GoldenCrossMAConfig

CONFIG = GoldenCrossConfigDTO(ma_config=GoldenCrossMAConfig(short_period=5, long_period=60))
CAPITAL = BacktestConfigDTO(initial_capital=Decimal("10000000"))


def _crafted_df() -> pd.DataFrame:
    closes: list[float] = []
    p = 100.0
    for _ in range(90):
        p *= 1.004
        closes.append(p)
    for _ in range(3):
        p *= 0.965
        closes.append(p)
    for _ in range(30):
        p *= 1.006
        closes.append(p)
    for _ in range(40):
        p *= 1.004
        closes.append(p)
    for _ in range(30):
        p *= 0.97
        closes.append(p)
    n = len(closes)
    dates = pd.date_range("2023-01-02", periods=n, freq="B")
    close = np.array(closes, dtype=float)
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


def _panels(symbols: list[str]) -> dict[str, pd.DataFrame]:
    df = _crafted_df()
    return {s: df.copy() for s in symbols}


def test_baseline_enters_without_gate():
    engine = PortfolioParityEngine(
        CONFIG, PortfolioConstraints(max_positions=3, allocation_ratio=0.1)
    )
    out = engine.run(_panels(["A", "B", "C"]), CAPITAL)
    assert out.entered_positions > 0  # 게이트 없으면 진입 발생(대조군)


def test_empty_allowed_dates_blocks_all_entries():
    engine = PortfolioParityEngine(
        CONFIG, PortfolioConstraints(max_positions=3, allocation_ratio=0.1)
    )
    out = engine.run(_panels(["A", "B", "C"]), CAPITAL, entry_allowed_dates=set())

    assert out.entered_positions == 0  # 전 거래일 차단 → 진입 0
    assert all(r.reason == "regime_block" for r in out.rejected)
    assert len(out.rejected) > 0


def test_full_calendar_allowed_matches_baseline():
    panels = _panels(["A", "B", "C"])
    all_dates = {ts.date() for ts in _crafted_df()["timestamp"]}
    engine = PortfolioParityEngine(
        CONFIG, PortfolioConstraints(max_positions=3, allocation_ratio=0.1)
    )

    gated = engine.run(
        {k: v.copy() for k, v in panels.items()}, CAPITAL, entry_allowed_dates=all_dates
    )
    base = PortfolioParityEngine(
        CONFIG, PortfolioConstraints(max_positions=3, allocation_ratio=0.1)
    ).run({k: v.copy() for k, v in panels.items()}, CAPITAL)

    # 모든 거래일 허용 → regime_block 없음, 진입 수 동일
    assert not any(r.reason == "regime_block" for r in gated.rejected)
    assert gated.entered_positions == base.entered_positions


def test_runner_allowed_dates_for():
    bench = _crafted_df()
    cand_filtered = WalkForwardCandidate(
        "f", CONFIG, regime_filter=RegimeEntryFilter(use_ma=True, ma_period=20)
    )
    runner = WalkForwardRunner(candidates=[cand_filtered], benchmark=bench)

    # 필터+벤치 → set 반환(캐시 동작), 필터 None → None
    allowed = runner._allowed_dates_for(cand_filtered.regime_filter)
    assert isinstance(allowed, set) and len(allowed) > 0
    assert runner._allowed_dates_for(None) is None

    # 벤치 없으면 None(러너에 benchmark 미주입)
    runner_no_bench = WalkForwardRunner(candidates=[cand_filtered])
    assert runner_no_bench._allowed_dates_for(cand_filtered.regime_filter) is None
