# -*- coding: utf-8 -*-
"""
Leverage Overlay - 추세 상태 조건부 레버리지 (연구용, 라이브 경로 아님)

사전 등록: docs/plans/leverage-overlay-preregistration.md
노출 배수 e(0=현금, 1=지수, 2=합성 2배)를 신호 다음 날부터 보유한다.
  e배 일수익 = e·(r + div_d) − (e−1)·(rf_d + borrow_spread_d) − fee(e)_d     (e ≥ 1)
  현금(e=0)  = rf_d
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

import pandas as pd

from src.application.domain.backtest.state_overlay import TRADING_DAYS, rule_s1

ExposureRule = Callable[[pd.Series], pd.Series]


def rule_l1(close: pd.Series) -> pd.Series:
    """L1: S1 상승 상태면 2배, 아니면 현금."""
    return rule_s1(close) * 2.0


def rule_l2(close: pd.Series) -> pd.Series:
    """L2: S1 상승 상태면 2배, 아니면 1배."""
    return rule_s1(close) + 1.0


def rule_l3(close: pd.Series) -> pd.Series:
    """L3: 항상 2배(필터 없는 레버리지 대조군)."""
    return pd.Series(2.0, index=close.index)


def rule_bh(close: pd.Series) -> pd.Series:
    return pd.Series(1.0, index=close.index)


RULES: dict[str, ExposureRule] = {"L1": rule_l1, "L2": rule_l2, "L3": rule_l3, "BH": rule_bh}


@dataclass(frozen=True, slots=True)
class LeverageConfig:
    cost_rate: float = 0.0005
    dividend_yield: float = 0.017
    fee_1x: float = 0.0005
    fee_2x: float = 0.0064
    borrow_spread: float = 0.0
    rate_shift: float = 0.0


def _fee(exposure: pd.Series, cfg: LeverageConfig) -> pd.Series:
    """노출별 운용보수(연). 0은 무보수, 1~2 사이는 선형 보간."""
    e = exposure.clip(lower=0.0)
    fee = pd.Series(0.0, index=e.index)
    one = e > 0
    fee[one] = cfg.fee_1x + (e[one].clip(upper=2.0) - 1.0).clip(lower=0.0) * (cfg.fee_2x - cfg.fee_1x)
    return fee


def daily_returns(
    frame: pd.DataFrame,
    exposure_signal: pd.Series,
    cash_rates: Mapping[int, float],
    cfg: LeverageConfig,
) -> pd.DataFrame:
    dates = pd.to_datetime(frame["date"])
    close = frame["close"].astype(float)
    held = exposure_signal.shift(1).fillna(0.0)
    r = close.pct_change().fillna(0.0)
    rf = dates.dt.year.map(lambda y: cash_rates[int(y)] + cfg.rate_shift) / TRADING_DAYS
    div = cfg.dividend_yield / TRADING_DAYS
    borrow = (held - 1.0).clip(lower=0.0) * (rf + cfg.borrow_spread / TRADING_DAYS)
    invested = held.clip(upper=1.0)  # 차입 없이 투자한 부분(나머지 현금)
    cash_part = (1.0 - invested) * rf
    turnover = held.diff().abs().fillna(held.abs())
    ret = (
        held * (r + div)
        - borrow
        + cash_part
        - _fee(held, cfg) / TRADING_DAYS
        - turnover * cfg.cost_rate
    )
    return pd.DataFrame({"date": dates, "ret": ret, "rf": rf, "w": held})


def yearly_returns(daily: pd.DataFrame) -> dict[int, float]:
    g = daily.groupby(daily["date"].dt.year)["ret"]
    return {int(y): float((1.0 + s).prod() - 1.0) for y, s in g}


def evaluate_gates(d1: dict, cagr_beats_bh: list[bool]) -> dict[str, bool | str]:
    """사전 등록 §5. d1 = {"L1": metrics, "L3": metrics, "BH": metrics}."""
    l1, l3, bh = d1["L1"], d1["L3"], d1["BH"]
    g1 = l1["cagr"] >= bh["cagr"] + 0.02
    g2 = l1["mdd"] >= bh["mdd"] - 0.10
    g3 = l1["cagr"] >= l3["cagr"] and l1["mdd"] > l3["mdd"]
    g4 = sum(cagr_beats_bh) >= 2
    if g1 and g2 and g3 and g4:
        verdict = "GO"
    elif g1 and g4:
        verdict = "CONDITIONAL"
    else:
        verdict = "NO-GO"
    return {"G1": g1, "G2": g2, "G3": g3, "G4": g4, "verdict": verdict}
