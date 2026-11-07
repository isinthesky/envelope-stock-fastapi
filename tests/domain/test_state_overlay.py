"""state_overlay 연구 모듈 단위 테스트 (합성 데이터 — 홀드아웃 데이터와 무관)."""

import numpy as np
import pandas as pd
import pytest

from src.application.domain.backtest.state_overlay import (
    OverlayConfig,
    block_bootstrap_sharpe_diff,
    daily_returns,
    evaluate_gates,
    metrics,
    rule_bh,
    rule_s1,
    rule_s3,
    static_mix_returns,
)

RATES = {2020: 0.02, 2021: 0.02, 2022: 0.02}


def _frame(prices: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {"date": pd.bdate_range("2020-01-01", periods=len(prices)), "close": prices}
    )


def test_signal_is_applied_next_day_no_lookahead() -> None:
    frame = _frame([100, 110, 121])
    weights = pd.Series([1.0, 1.0, 1.0])
    out = daily_returns(frame, weights, RATES, OverlayConfig(cost_rate=0, dividend_yield=0))
    # 1일차 보유 비중은 0(전일 신호 없음) → 1일차 수익은 현금, 2일차부터 +10%
    assert out["w"].tolist() == [0.0, 1.0, 1.0]
    assert out["ret"].iloc[1] == pytest.approx(0.10)


def test_switch_cost_and_cash_interest() -> None:
    frame = _frame([100, 100, 100, 100])
    weights = pd.Series([1.0, 0.0, 0.0, 0.0])
    out = daily_returns(frame, weights, RATES, OverlayConfig(cost_rate=0.001, dividend_yield=0))
    # 1일차 진입 비용, 2일차 청산 비용
    assert out["ret"].iloc[1] == pytest.approx(-0.001)
    assert out["ret"].iloc[2] == pytest.approx(0.02 / 252 - 0.001)


def test_rules_warmup_and_partial_defense() -> None:
    close = pd.Series(np.linspace(100, 200, 300))
    s1 = rule_s1(close)
    assert s1.iloc[:164].eq(0).all() and s1.iloc[-1] == 1.0
    s3 = rule_s3(pd.Series(np.linspace(200, 100, 300)))
    assert set(s3.unique()) <= {0.5, 1.0}


def test_metrics_and_static_mix() -> None:
    rng = np.random.default_rng(1)
    prices = list(100 * np.cumprod(1 + rng.normal(0.0004, 0.01, 600)))
    frame = pd.DataFrame(
        {"date": pd.bdate_range("2020-01-01", periods=600), "close": prices}
    )
    cfg = OverlayConfig(cost_rate=0, dividend_yield=0)
    bh = daily_returns(frame, rule_bh(frame["close"]), RATES, cfg)
    xm = static_mix_returns(bh, 0.5, RATES, cfg)
    m_bh, m_xm = metrics(bh), metrics(xm)
    assert m_xm["mdd"] > m_bh["mdd"]  # 절반 노출은 낙폭이 작다
    point, lo, hi = block_bootstrap_sharpe_diff(bh, bh, n=50)
    assert point == pytest.approx(0.0) and lo <= 0 <= hi


def test_gate_verdicts() -> None:
    bh = {"mdd": -0.50, "sharpe": 0.40, "cagr": 0.08}
    good = {"mdd": -0.35, "sharpe": 0.42, "cagr": 0.07}
    xm = {"cagr": 0.06}
    assert evaluate_gates(good, bh, xm, [True, True, False])["verdict"] == "GO"
    weak = {**good, "sharpe": 0.30}
    assert evaluate_gates(weak, bh, xm, [True, True, True])["verdict"] == "CONDITIONAL"
    assert evaluate_gates({**good, "mdd": -0.45}, bh, xm, [True] * 3)["verdict"] == "NO-GO"
