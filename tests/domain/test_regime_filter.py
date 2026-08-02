# -*- coding: utf-8 -*-
"""RegimeEntryFilter / compute_allowed_entry_dates 단위 테스트."""

from datetime import datetime, timedelta

import pandas as pd

from src.application.domain.backtest.regime_filter import (
    RegimeEntryFilter,
    compute_allowed_entry_dates,
    wilder_adx_series,
)


def _bench(up_days: int, down_days: int) -> pd.DataFrame:
    base = datetime(2022, 1, 3)
    n = up_days + down_days
    dates = [base + timedelta(days=i) for i in range(n)]
    up = [100.0 + i * 0.5 for i in range(up_days)]
    down = [up[-1] - i * 0.8 for i in range(down_days)] if up else []
    close = up + down
    return pd.DataFrame(
        {
            "timestamp": dates,
            "open": close,
            "high": [c * 1.01 for c in close],
            "low": [c * 0.99 for c in close],
            "close": close,
            "volume": [1000] * n,
        }
    )


def test_none_filter_returns_none():
    df = _bench(250, 100)
    assert compute_allowed_entry_dates(df, None) is None


def test_all_gates_off_returns_none():
    df = _bench(250, 100)
    f = RegimeEntryFilter(use_ma=False, use_adx=False)
    assert compute_allowed_entry_dates(df, f) is None


def test_ma_gate_blocks_downtrend_allows_uptrend():
    df = _bench(250, 100)
    f = RegimeEntryFilter(use_ma=True, ma_period=200, use_adx=False)
    allowed = compute_allowed_entry_dates(df, f)
    assert allowed is not None

    all_dates = [ts.date() for ts in df["timestamp"]]
    # 하락 후반부는 close<MA200 → 전량 차단
    late = all_dates[-40:]
    assert all(d not in allowed for d in late)
    # 상승 후반부(MA 확정 이후)는 close>MA200 → 허용
    mid_up = all_dates[210:245]
    assert all(d in allowed for d in mid_up)


def test_ma_warmup_is_fail_open():
    df = _bench(250, 100)
    f = RegimeEntryFilter(use_ma=True, ma_period=200, use_adx=False)
    allowed = compute_allowed_entry_dates(df, f)
    all_dates = [ts.date() for ts in df["timestamp"]]
    # MA200 미확정(초기 199일)은 fail-open(허용)
    assert all(d in allowed for d in all_dates[:150])


def test_adx_series_valid_and_warmup_nan():
    df = _bench(300, 60)
    adx = wilder_adx_series(df, 14)
    assert adx.iloc[: 2 * 14].isna().all()  # 워밍업 NaN
    assert adx.notna().sum() > 0


def test_empty_benchmark_returns_none():
    f = RegimeEntryFilter(use_ma=True)
    assert compute_allowed_entry_dates(pd.DataFrame(), f) is None


def test_filter_is_hashable():
    f1 = RegimeEntryFilter(use_ma=True, ma_period=200)
    f2 = RegimeEntryFilter(use_ma=True, ma_period=200)
    cache = {f1: "x"}
    assert cache[f2] == "x"  # 동일값 → 동일 해시(캐시 키)


def test_describe_labels():
    assert RegimeEntryFilter(use_ma=True, use_adx=False).describe() == "MA200"
    assert "ADX14" in RegimeEntryFilter(use_ma=False, use_adx=True).describe()
    assert RegimeEntryFilter(use_ma=False, use_adx=False).describe() == "no-filter"
