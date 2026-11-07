# -*- coding: utf-8 -*-
"""
Market Regime - 골든크로스 신규 진입 국면 게이트 (스캔·실주문 공용)

walk-forward A/B가 검증한 `RegimeEntryFilter`를 운영 설정(gc_regime_mode/ma/adx)으로 구성하고,
최신 벤치마크 바 기준으로 신규 진입 허용 여부를 판정한다.

- 스캔/알림 경로: 데이터 불량 시 fail-open (후보를 숨기지 않는다).
- 실주문 경로: 데이터 불량 시 fail-closed (신규 매수 차단). 청산은 이 게이트와 무관하다.
"""

import logging
from datetime import datetime, timedelta, timezone

import pandas as pd

from src.application.domain.backtest.regime_filter import (
    RegimeEntryFilter,
    is_entry_allowed_latest,
)
from src.settings.config import settings

logger = logging.getLogger(__name__)

# 벤치 최신 바가 이보다 오래되면 신뢰하지 않는다(연휴 고려).
MAX_BENCH_AGE = timedelta(days=7)


def build_regime_filter() -> RegimeEntryFilter:
    """운영 설정으로 진입 국면 필터를 구성한다. 알 수 없는 mode는 권장값(adx)로 폴백."""
    mode = settings.gc_regime_mode
    use_ma = mode in ("ma", "ma_adx")
    use_adx = mode in ("adx", "ma_adx")
    if not use_ma and not use_adx:  # 방어: 미지의 mode → ADX(권장)
        use_adx = True
    return RegimeEntryFilter(
        use_ma=use_ma,
        ma_period=settings.gc_regime_ma,
        use_adx=use_adx,
        adx_period=settings.gc_regime_adx_period,
        adx_min=settings.gc_regime_adx_min,
    )


def market_regime_ok(bench_df: pd.DataFrame | None, *, fail_open: bool) -> bool:
    """최신 벤치 바 기준 신규 진입 허용 여부.

    벤치가 없거나(실 OHLC 필요) 최신 바가 stale/미래이거나 판정 중 오류가 나면
    `fail_open` 값을 그대로 반환한다.
    """
    if bench_df is None or getattr(bench_df, "empty", True):
        logger.warning("[regime] benchmark unavailable → %s", "allow" if fail_open else "block")
        return fail_open
    try:
        last = bench_df["timestamp"].iloc[-1]
        if getattr(last, "tzinfo", None) is None:
            last = last.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - last
        if age > MAX_BENCH_AGE or age < -timedelta(days=1):
            logger.warning(
                "[regime] benchmark stale/future (last=%s) → %s",
                last,
                "allow" if fail_open else "block",
            )
            return fail_open
        return is_entry_allowed_latest(bench_df, build_regime_filter())
    except Exception:  # noqa: BLE001 - 판정 불가 시 정책값 반환
        logger.exception("[regime] evaluation failed → %s", "allow" if fail_open else "block")
        return fail_open
