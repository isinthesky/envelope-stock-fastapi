# -*- coding: utf-8 -*-
"""
State Overlay - 추세 상태 기반 노출 조절 오버레이 (연구용, 라이브 경로 아님)

사전 등록 문서: docs/plans/state-overlay-preregistration.md (규칙·비용·지표·판정 기준 고정).
단일 가격 시계열(지수/ETF)에 대해 비중 w ∈ [0,1]을 보유하고 나머지는 현금이자를 받는다.

- 신호는 t일 종가로 확정하고 t+1일 수익부터 반영한다(미래 정보 없음).
- 비용: 편도 cost_rate × |Δw| (비중이 바뀐 날 차감).
- 배당 근사: 보유 비중만큼 일별 dividend_yield/252를 가산(지수 가격수익 보정).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

import numpy as np
import pandas as pd

TRADING_DAYS = 252

RuleFn = Callable[[pd.Series], pd.Series]


def rule_s1(close: pd.Series) -> pd.Series:
    """S1: MA55 > MA165 이면 1, 아니면 0 (워밍업 구간은 0)."""
    ma_s, ma_l = close.rolling(55).mean(), close.rolling(165).mean()
    return (ma_s > ma_l).astype(float)


def rule_s2(close: pd.Series) -> pd.Series:
    """S2: 종가 > MA200 이면 1, 아니면 0."""
    return (close > close.rolling(200).mean()).astype(float)


def rule_s3(close: pd.Series) -> pd.Series:
    """S3: S1 상태면 1, 아니면 0.5 (워밍업 구간은 0.5)."""
    return rule_s1(close).map({1.0: 1.0, 0.0: 0.5})


def rule_bh(close: pd.Series) -> pd.Series:
    return pd.Series(1.0, index=close.index)


RULES: dict[str, RuleFn] = {"S1": rule_s1, "S2": rule_s2, "S3": rule_s3, "BH": rule_bh}


@dataclass(frozen=True, slots=True)
class OverlayConfig:
    cost_rate: float = 0.0005
    dividend_yield: float = 0.017
    cash_rate_shift: float = 0.0


def daily_returns(
    frame: pd.DataFrame,
    weights: pd.Series,
    cash_rates: Mapping[int, float],
    config: OverlayConfig,
) -> pd.DataFrame:
    """frame(date, close) + 신호 비중 → 일별 전략 수익.

    weights는 frame과 같은 인덱스의 "t일 종가 기준 목표 비중"이다. 실제 보유는 하루 늦게 적용한다.
    """
    dates = pd.to_datetime(frame["date"])
    close = frame["close"].astype(float)
    held = weights.shift(1).fillna(0.0)
    price_r = close.pct_change().fillna(0.0)
    rf_annual = dates.dt.year.map(lambda y: cash_rates[int(y)] + config.cash_rate_shift)
    rf = rf_annual / TRADING_DAYS
    div = config.dividend_yield / TRADING_DAYS
    turnover = held.diff().abs().fillna(held.abs())
    ret = held * (price_r + div) + (1.0 - held) * rf - turnover * config.cost_rate
    return pd.DataFrame({"date": dates, "ret": ret, "rf": rf, "w": held})


def static_mix_returns(
    bh: pd.DataFrame, exposure: float, cash_rates: Mapping[int, float], config: OverlayConfig
) -> pd.DataFrame:
    """XM: 평균 노출 ē로 고정한 정적 혼합(매일 리밸런스, 비용 0 — 낙관적 기준)."""
    asset = bh["ret"]  # BH: 비중 1, 비용은 첫날만
    ret = exposure * asset + (1.0 - exposure) * bh["rf"]
    return pd.DataFrame({"date": bh["date"], "ret": ret, "rf": bh["rf"], "w": exposure})


def metrics(daily: pd.DataFrame) -> dict[str, float | int | None]:
    r, rf = daily["ret"], daily["rf"]
    if len(r) < 2:
        return {}
    equity = (1.0 + r).cumprod()
    years = len(r) / TRADING_DAYS
    cagr = float(equity.iloc[-1] ** (1.0 / years) - 1.0)
    std = float(r.std(ddof=1))
    sharpe = float((r - rf).mean() / std * np.sqrt(TRADING_DAYS)) if std > 0 else 0.0
    drawdown = equity / equity.cummax() - 1.0
    mdd = float(drawdown.min())
    w = daily["w"] if isinstance(daily["w"], pd.Series) else pd.Series(daily["w"], index=r.index)
    switches = int((w.diff().abs() > 1e-12).sum())
    return {
        "cagr": cagr,
        "sharpe": sharpe,
        "mdd": mdd,
        "avg_exposure": float(w.mean()),
        "switches": switches,
        "longest_recovery_days": _longest_underwater(equity),
        "days": int(len(r)),
    }


def _longest_underwater(equity: pd.Series) -> int:
    peak = equity.cummax()
    under = (equity < peak).astype(int).to_numpy()
    longest = current = 0
    for flag in under:
        current = current + 1 if flag else 0
        longest = max(longest, current)
    return int(longest)


def block_bootstrap_sharpe_diff(
    a: pd.DataFrame, b: pd.DataFrame, block: int = 63, n: int = 5000, seed: int = 0
) -> tuple[float, float, float]:
    """정상 블록 부트스트랩으로 Sharpe(a) − Sharpe(b)의 (점추정, 2.5%, 97.5%)."""
    ea = (a["ret"] - a["rf"]).to_numpy()
    eb = (b["ret"] - b["rf"]).to_numpy()
    ra, rb = a["ret"].to_numpy(), b["ret"].to_numpy()
    length = len(ea)
    rng = np.random.default_rng(seed)

    def _sr(excess: np.ndarray, raw: np.ndarray) -> float:
        sd = raw.std(ddof=1)
        return float(excess.mean() / sd * np.sqrt(TRADING_DAYS)) if sd > 0 else 0.0

    point = _sr(ea, ra) - _sr(eb, rb)
    diffs = np.empty(n)
    p = 1.0 / block
    for i in range(n):
        idx = np.empty(length, dtype=int)
        pos = rng.integers(length)
        for t in range(length):
            if t > 0 and rng.random() < p:
                pos = rng.integers(length)
            idx[t] = pos
            pos = (pos + 1) % length
        diffs[i] = _sr(ea[idx], ra[idx]) - _sr(eb[idx], rb[idx])
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return point, float(lo), float(hi)


def evaluate_gates(s1: dict, bh: dict, xm: dict, sub_g1: list[bool]) -> dict[str, bool | str]:
    """사전 등록 §5 판정."""
    g1 = s1["mdd"] >= bh["mdd"] + 0.10
    g2 = s1["sharpe"] >= bh["sharpe"] - 0.05
    g3 = s1["cagr"] >= xm["cagr"]
    g4 = sum(sub_g1) >= 2
    if g1 and g2 and g3 and g4:
        verdict = "GO"
    elif g1 and g4:
        verdict = "CONDITIONAL"
    else:
        verdict = "NO-GO"
    return {"G1": g1, "G2": g2, "G3": g3, "G4": g4, "verdict": verdict}
