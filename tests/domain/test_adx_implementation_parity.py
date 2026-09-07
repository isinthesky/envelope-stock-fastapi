# -*- coding: utf-8 -*-
"""ADX 두 구현의 비동치 특성화 테스트 (P1-B).

`TechnicalIndicators.calculate_adx`(SMA 시딩 Wilder 재귀 + DX 재평활, 마지막 1값)와
`regime_filter.wilder_adx_series`(첫 값 시딩 ewm, 전 구간 시리즈)는 **동치가 아니다.**
'동치니까 하나로 합치자'는 리팩터링은 백테스트/워크포워드 진입 게이트 결과를 바꾸므로,
통합 대신 "의도적으로 다르며 각자의 계약을 지킨다"를 코드로 못박는다.
"""

import math

import pandas as pd
import pytest

from src.application.common.indicators import TechnicalIndicators
from src.application.domain.backtest.regime_filter import wilder_adx_series

PERIOD = 14

# wilder_adx_series(400봉 합성 OHLC)의 마지막 5개 값. 도커 테스트 이미지에서 실측.
GOLDEN_ADX_TAIL: list[float] = [44.550424, 45.282945, 46.08174, 46.922474, 47.81772]


def _synthetic_ohlc(n: int) -> pd.DataFrame:
    """결정적(난수 없음) 합성 OHLC. 추세 + 사인 진동 + 소폭 톱니."""
    rows = []
    for i in range(n):
        base = 100.0 + 0.08 * i + 8.0 * math.sin(i / 9.0) + 1.5 * math.sin(i / 2.3)
        rows.append({"high": base + 1.2, "low": base - 1.1, "close": base})
    return pd.DataFrame(rows)


def _scalar_adx(df: pd.DataFrame) -> float | None:
    res = TechnicalIndicators.calculate_adx(
        list(df["high"].astype(float)),
        list(df["low"].astype(float)),
        list(df["close"].astype(float)),
        PERIOD,
    )
    return None if res is None else float(res["adx"])


def test_two_adx_implementations_diverge_on_short_windows() -> None:
    """짧은 구간에서는 시딩 차이로 유의미하게 벌어진다(통합 불가 근거)."""
    short_df = _synthetic_ohlc(60)
    scalar = _scalar_adx(short_df)
    series = float(wilder_adx_series(short_df, PERIOD).iloc[-1])

    assert scalar is not None
    # 실측 diff ≈ 0.99 ADX 포인트. '동치'라고 착각해 통합하는 것을 막는다.
    assert abs(scalar - series) > 0.05


def test_two_adx_implementations_converge_on_long_windows() -> None:
    """긴 구간에서는 수렴한다 — 다만 '수렴'이 '동치'는 아니다."""
    long_df = _synthetic_ohlc(400)
    scalar = _scalar_adx(long_df)
    series = float(wilder_adx_series(long_df, PERIOD).iloc[-1])

    assert scalar is not None
    # 실측 diff ≈ 0.0023 (calculate_adx의 round(2) 오차 포함)
    assert abs(scalar - series) < 0.05


def test_scalar_adx_contract_rounds_to_two_decimals() -> None:
    """calculate_adx는 소수 2자리 반올림 계약을 유지한다(표시/알림용)."""
    res = TechnicalIndicators.calculate_adx(
        list(_synthetic_ohlc(400)["high"].astype(float)),
        list(_synthetic_ohlc(400)["low"].astype(float)),
        list(_synthetic_ohlc(400)["close"].astype(float)),
        PERIOD,
    )
    assert res is not None
    assert res["adx"] == round(res["adx"], 2)


def test_regime_adx_series_golden_values_are_frozen() -> None:
    """regime_filter 출력 자체를 골든값으로 고정(백테스트 결과 드리프트 방지)."""
    adx = wilder_adx_series(_synthetic_ohlc(400), PERIOD)
    tail = [round(float(v), 6) for v in adx.iloc[-5:]]
    assert tail == pytest.approx(GOLDEN_ADX_TAIL, abs=1e-6)


def test_regime_adx_warmup_is_nan() -> None:
    """워밍업 마스킹(2*period)은 fail-open 계약의 일부다.

    calculate_adx에는 이 마스킹이 없다 — 두 구현의 계약 차이 중 하나다.
    """
    adx = wilder_adx_series(_synthetic_ohlc(300), PERIOD)
    assert adx.iloc[: 2 * PERIOD].isna().all()
    assert adx.notna().sum() > 0
