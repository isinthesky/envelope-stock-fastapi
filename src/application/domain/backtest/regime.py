# -*- coding: utf-8 -*-
"""
Market Regime Decomposition (P4/§8) — 국면별 OOS 성과 격리

walk-forward OOS 성과를 벤치마크(예: KODEX 200) 기준 bull/bear/chop로 분해한다.
강세장의 높은 수익은 무의미하고, **2022 약세장 구간의 OOS 성과/MDD가 실질
합격 판정의 중심**이라는 원칙(설계 §8)을 데이터로 뒷받침한다.

순수 numpy/pandas(외부 의존 없음).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, cast

import numpy as np
import pandas as pd

BULL = "bull"
BEAR = "bear"
CHOP = "chop"


def _to_date(ts: Any) -> date:
    return cast(date, ts.date() if hasattr(ts, "date") else ts)


def classify_regimes(
    benchmark_df: pd.DataFrame,
    *,
    long_ma: int = 200,
    band: float = 0.03,
) -> dict[date, str]:
    """벤치마크 종가로 거래일별 국면을 분류한다.

    ratio = close / MA_long - 1
      ratio >  band → bull
      ratio < -band → bear
      그 외        → chop
    MA_long 이 아직 유효하지 않은 초반 구간은 chop으로 둔다.
    """
    if benchmark_df is None or benchmark_df.empty or "close" not in benchmark_df.columns:
        return {}
    df = benchmark_df.sort_values("timestamp").reset_index(drop=True)
    ma = df["close"].rolling(window=long_ma).mean()
    labels: dict[date, str] = {}
    for i in range(len(df)):
        d = _to_date(df["timestamp"].iloc[i])
        m = ma.iloc[i]
        if pd.isna(m) or m <= 0:
            labels[d] = CHOP
            continue
        ratio = float(df["close"].iloc[i]) / float(m) - 1.0
        if ratio > band:
            labels[d] = BULL
        elif ratio < -band:
            labels[d] = BEAR
        else:
            labels[d] = CHOP
    return labels


@dataclass(frozen=True, slots=True)
class RegimeMetrics:
    regime: str
    n_days: int
    total_return: float  # 국면 구간 복리 수익률(%)
    daily_sharpe: float
    mdd: float  # 국면 하위 자산곡선 최대낙폭(%)


def _metrics_for(regime: str, rets: list[float]) -> RegimeMetrics:
    if not rets:
        return RegimeMetrics(regime, 0, 0.0, 0.0, 0.0)
    arr = np.asarray(rets, dtype=float)
    # 복리 자산곡선(1 시작)
    equity = np.cumprod(1.0 + arr)
    total_return = float((equity[-1] - 1.0) * 100.0)
    sd = float(arr.std(ddof=1)) if arr.size > 1 else 0.0
    sharpe = float(arr.mean() / sd) if sd > 0 else 0.0
    running_max = np.maximum.accumulate(equity)
    drawdowns = equity / running_max - 1.0
    mdd = float(drawdowns.min() * 100.0)
    return RegimeMetrics(
        regime=regime,
        n_days=int(arr.size),
        total_return=round(total_return, 2),
        daily_sharpe=round(sharpe, 3),
        mdd=round(mdd, 2),
    )


def decompose_by_regime(
    dated_returns: Sequence[tuple[datetime | date, float]],
    regimes: dict[date, str],
) -> dict[str, RegimeMetrics]:
    """OOS 일별수익을 국면별로 묶어 성과지표를 계산한다.

    Args:
        dated_returns: (거래일, 일별수익) 리스트 — OOS 연속 수익
        regimes: 거래일 → 국면 라벨
    """
    buckets: dict[str, list[float]] = {BULL: [], BEAR: [], CHOP: []}
    for dt, r in dated_returns:
        d = _to_date(dt)
        label = regimes.get(d, CHOP)
        buckets.setdefault(label, []).append(r)
    return {regime: _metrics_for(regime, rets) for regime, rets in buckets.items()}


def regime_summary_dict(decomp: dict[str, RegimeMetrics]) -> dict:
    """리포트/직렬화용 요약 dict."""
    return {
        regime: {
            "n_days": m.n_days,
            "total_return": m.total_return,
            "daily_sharpe": m.daily_sharpe,
            "mdd": m.mdd,
        }
        for regime, m in decomp.items()
    }
