"""leverage_overlay 연구 모듈 단위 테스트 (합성 데이터)."""

import pandas as pd
import pytest

from src.application.domain.backtest.leverage_overlay import (
    LeverageConfig,
    daily_returns,
    evaluate_gates,
    rule_l1,
    rule_l2,
)

RATES = {2020: 0.0252}
ZERO = LeverageConfig(cost_rate=0, dividend_yield=0, fee_1x=0, fee_2x=0)


def _frame(prices: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"date": pd.bdate_range("2020-01-01", periods=len(prices)), "close": prices})


def test_two_x_return_pays_financing_on_borrowed_unit() -> None:
    frame = _frame([100, 100, 101])
    out = daily_returns(frame, pd.Series([2.0, 2.0, 2.0]), RATES, ZERO)
    rf = 0.0252 / 252
    assert out["w"].tolist() == [0.0, 2.0, 2.0]
    assert out["ret"].iloc[1] == pytest.approx(-rf)  # 가격 불변 → 차입이자만
    assert out["ret"].iloc[2] == pytest.approx(2 * 0.01 - rf)


def test_cash_and_one_x() -> None:
    frame = _frame([100, 110])
    cash = daily_returns(frame, pd.Series([0.0, 0.0]), RATES, ZERO)
    one = daily_returns(frame, pd.Series([1.0, 1.0]), RATES, ZERO)
    assert cash["ret"].iloc[1] == pytest.approx(0.0252 / 252)
    assert one["ret"].iloc[1] == pytest.approx(0.10)


def test_fee_and_switch_cost() -> None:
    frame = _frame([100, 100])
    cfg = LeverageConfig(cost_rate=0.001, dividend_yield=0, fee_1x=0.0, fee_2x=0.0252, borrow_spread=0)
    out = daily_returns(frame, pd.Series([2.0, 2.0]), {2020: 0.0}, cfg)
    assert out["ret"].iloc[1] == pytest.approx(-0.0252 / 252 - 2 * 0.001)


def test_rules_shape() -> None:
    close = pd.Series(range(1, 301), dtype=float)
    assert rule_l1(close).iloc[-1] == 2.0 and rule_l1(close).iloc[0] == 0.0
    assert rule_l2(close).iloc[0] == 1.0


def test_gates() -> None:
    bh = {"cagr": 0.08, "mdd": -0.50}
    d1 = {"BH": bh, "L1": {"cagr": 0.12, "mdd": -0.55}, "L3": {"cagr": 0.10, "mdd": -0.80}}
    assert evaluate_gates(d1, [True, True, False])["verdict"] == "GO"
    d1_risky = {**d1, "L1": {"cagr": 0.12, "mdd": -0.70}}
    assert evaluate_gates(d1_risky, [True, True, True])["verdict"] == "CONDITIONAL"
    assert evaluate_gates(d1, [True, False, False])["verdict"] == "NO-GO"
