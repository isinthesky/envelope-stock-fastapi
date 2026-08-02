# -*- coding: utf-8 -*-
"""P4 국면 분해 테스트 — regime.py."""

from datetime import date, datetime

import numpy as np
import pandas as pd

from src.application.domain.backtest.regime import (
    BEAR,
    BULL,
    CHOP,
    classify_regimes,
    decompose_by_regime,
    regime_summary_dict,
)


def _bench(closes: list[float]) -> pd.DataFrame:
    n = len(closes)
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2021-01-04", periods=n, freq="B"),
            "close": np.array(closes, dtype=float),
        }
    )


def test_classify_regimes_bull_bear_chop():
    # 250 상승 → bull, 이후 급락 지속 → bear
    up = list(100 * 1.004 ** np.arange(250))
    down = list(up[-1] * 0.99 ** np.arange(1, 120))
    labels = classify_regimes(_bench(up + down), long_ma=200, band=0.03)
    vals = list(labels.values())
    # 초반(MA 미형성)은 chop, 상승 성숙 구간엔 bull, 급락 구간엔 bear 존재
    assert BULL in vals
    assert BEAR in vals
    assert vals[0] == CHOP  # MA 미형성 초반


def test_decompose_groups_returns_by_regime():
    regimes = {
        date(2022, 1, 3): BULL,
        date(2022, 1, 4): BULL,
        date(2022, 1, 5): BEAR,
        date(2022, 1, 6): BEAR,
        date(2022, 1, 7): CHOP,
    }
    dated = [
        (datetime(2022, 1, 3), 0.01),
        (datetime(2022, 1, 4), 0.01),
        (datetime(2022, 1, 5), -0.02),
        (datetime(2022, 1, 6), -0.03),
        (datetime(2022, 1, 7), 0.0),
    ]
    decomp = decompose_by_regime(dated, regimes)
    assert decomp[BULL].n_days == 2
    assert decomp[BEAR].n_days == 2
    assert decomp[BULL].total_return > 0
    assert decomp[BEAR].total_return < 0
    assert decomp[BEAR].mdd < 0  # 약세장 낙폭 음수

    summ = regime_summary_dict(decomp)
    assert summ[BEAR]["n_days"] == 2
    assert set(summ.keys()) >= {BULL, BEAR, CHOP}


def test_empty_benchmark_returns_empty():
    assert classify_regimes(pd.DataFrame()) == {}
    assert decompose_by_regime([], {})[BULL].n_days == 0
