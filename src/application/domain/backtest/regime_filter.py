# -*- coding: utf-8 -*-
"""
Regime Entry Filter (P4+) — 하락/횡보장 진입 회피 게이트

walk-forward 엔진의 **진입(신규 매수)만** 시장 국면으로 차단하는 필터. 청산은
막지 않는다(보유는 정상 매도 규칙대로 빠져나옴). 라이브 `_market_regime_up`
(KOSPI>MA)와 같은 사상을 확장해 두 손실 국면을 동시에 겨냥한다:

    - MA 게이트  : 벤치(예: KODEX200) 종가 > MA(ma_period) 일 때만 진입  → 하락장 회피
    - ADX 게이트 : 벤치 추세강도 ADX(adx_period) ≥ adx_min 일 때만 진입 → 횡보장 whipsaw 회피

두 게이트는 AND로 결합한다(use_* 로 개별 on/off). 워밍업(지표 미확정) 구간은
라이브와 동일하게 **fail-open(진입 허용)** 으로 둔다.

주의: 이 모듈은 self-contained(순수 계산). DB/FastAPI 의존 없음.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, cast

import pandas as pd


@dataclass(frozen=True, slots=True)
class RegimeEntryFilter:
    """진입 국면 필터 설정(frozen → 해시 가능, 캐시 키로 사용)."""

    use_ma: bool = True
    ma_period: int = 200
    use_adx: bool = False
    adx_period: int = 14
    adx_min: float = 20.0

    def describe(self) -> str:
        parts: list[str] = []
        if self.use_ma:
            parts.append(f"MA{self.ma_period}")
        if self.use_adx:
            parts.append(f"ADX{self.adx_period}≥{self.adx_min:g}")
        return "+".join(parts) if parts else "no-filter"


def _row_date(ts: Any) -> date:
    return cast(date, ts.date() if hasattr(ts, "date") else ts)


def wilder_adx_series(df: pd.DataFrame, period: int) -> pd.Series:
    """Wilder ADX 시리즈(행 정렬 기준). high/low/close 컬럼 필요.

    TechnicalIndicators.calculate_adx와 동일한 Wilder 평활(ewm alpha=1/period)을
    사용하되, 마지막 1값이 아니라 **전 구간 시리즈**를 반환한다(진입일별 판정용).
    데이터 부족 구간은 NaN(호출측에서 fail-open 처리).
    """
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)

    prev_close = close.shift(1)
    tr = pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(
        axis=1
    )

    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = ((up_move > down_move) & (up_move > 0)) * up_move
    minus_dm = ((down_move > up_move) & (down_move > 0)) * down_move

    alpha = 1.0 / period
    atr = tr.ewm(alpha=alpha, adjust=False).mean()
    plus_di = 100.0 * plus_dm.ewm(alpha=alpha, adjust=False).mean() / atr
    minus_di = 100.0 * minus_dm.ewm(alpha=alpha, adjust=False).mean() / atr

    di_sum = (plus_di + minus_di).replace(0.0, pd.NA)
    dx = 100.0 * (plus_di - minus_di).abs() / di_sum
    adx = dx.ewm(alpha=alpha, adjust=False).mean()
    # 최소 데이터 미달 구간은 신뢰 불가 → NaN(fail-open)
    adx.iloc[: 2 * period] = float("nan")
    return adx


def compute_allowed_entry_dates(
    benchmark_df: pd.DataFrame | None, filt: RegimeEntryFilter | None
) -> set[date] | None:
    """진입 허용 거래일 집합을 계산한다.

    반환:
        - None: 필터/벤치 없음 → 게이트 미적용(엔진이 fail-open으로 전량 허용)
        - set[date]: 진입 허용일. 이 집합에 없는 날은 신규 진입 차단.

    워밍업(MA/ADX 미확정) 구간은 fail-open(허용)으로 둔다(라이브 정합).
    """
    if filt is None or benchmark_df is None or benchmark_df.empty:
        return None
    if not (filt.use_ma or filt.use_adx):
        return None
    if "close" not in benchmark_df.columns or "timestamp" not in benchmark_df.columns:
        return None

    df = benchmark_df.sort_values("timestamp").reset_index(drop=True)
    close = df["close"].astype(float)
    dates = [_row_date(ts) for ts in df["timestamp"]]

    # MA 게이트: close > MA. 미확정(NaN) → 허용(fail-open)
    if filt.use_ma:
        ma = close.rolling(window=filt.ma_period).mean()
        ma_ok = (close > ma) | ma.isna()
    else:
        ma_ok = pd.Series(True, index=df.index)

    # ADX 게이트: high/low 없으면 게이트 비활성(허용)
    if filt.use_adx and {"high", "low"}.issubset(df.columns):
        adx = wilder_adx_series(df, filt.adx_period)
        adx_ok = (adx >= filt.adx_min) | adx.isna()
    else:
        adx_ok = pd.Series(True, index=df.index)

    allowed_mask = ma_ok & adx_ok
    return {d for d, ok in zip(dates, allowed_mask) if bool(ok)}


def is_entry_allowed_latest(
    benchmark_df: pd.DataFrame | None, filt: RegimeEntryFilter | None
) -> bool:
    """**최신 바** 기준 진입 허용 여부(라이브 스캔용). 백테스트와 동일 수식 재사용.

    필터 없음 / 벤치 없음 / 지표 미확정(워밍업)은 fail-open(True). 최신 바에서
    게이트를 명시적으로 위반할 때만 False.
    """
    allowed = compute_allowed_entry_dates(benchmark_df, filt)
    if allowed is None or benchmark_df is None or benchmark_df.empty:
        return True
    last_ts = benchmark_df.sort_values("timestamp")["timestamp"].iloc[-1]
    return _row_date(last_ts) in allowed
