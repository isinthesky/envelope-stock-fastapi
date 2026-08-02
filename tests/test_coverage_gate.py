# -*- coding: utf-8 -*-
"""Coverage Gate 단위 테스트 (P1) — 순수 로직, DB/API 비의존."""

from datetime import date, datetime

import pandas as pd

from src.application.domain.backtest.coverage_gate import (
    CoverageParams,
    build_coverage_report,
    evaluate_symbol_coverage,
    trading_days_from_df,
    weekday_calendar,
)

PARAMS = CoverageParams(min_bars=10, min_coverage_rate=0.98)


def _cal(days: list[str]) -> set[date]:
    return {date.fromisoformat(d) for d in days}


def test_full_coverage_symbol_included():
    cal = weekday_calendar(date(2024, 1, 1), date(2024, 3, 1))  # ~44 weekdays
    v = evaluate_symbol_coverage(
        symbol="069500", symbol_dates=set(cal), calendar_dates=cal, params=PARAMS
    )
    assert v.included is True
    assert v.reasons == ()
    assert v.coverage_rate == 1.0
    assert v.bars == len(cal)


def test_low_coverage_excluded_with_reason():
    cal = weekday_calendar(date(2024, 1, 1), date(2024, 3, 1))
    # 절반만 보유 → 커버리지 ~50% < 98% → 제외
    partial = set(sorted(cal)[: len(cal) // 2])
    v = evaluate_symbol_coverage(
        symbol="X", symbol_dates=partial, calendar_dates=cal, params=PARAMS
    )
    assert v.included is False
    assert any("low_coverage" in r for r in v.reasons)


def test_insufficient_bars_excluded():
    cal = weekday_calendar(date(2024, 1, 1), date(2024, 1, 8))  # 6 weekdays < min_bars 10
    v = evaluate_symbol_coverage(
        symbol="NEW", symbol_dates=set(cal), calendar_dates=cal, params=PARAMS
    )
    assert v.included is False
    assert any("insufficient_bars" in r for r in v.reasons)


def test_dates_outside_calendar_do_not_inflate():
    cal = _cal(["2024-01-02", "2024-01-03", "2024-01-04"])
    # 종목이 달력 외 날짜(주말/장외)만 잔뜩 가져도 분자에 포함되지 않음
    sym = _cal(["2024-01-02", "2024-01-06", "2024-01-07", "2024-01-13"])
    v = evaluate_symbol_coverage(
        symbol="Y",
        symbol_dates=sym,
        calendar_dates=cal,
        params=CoverageParams(min_bars=1, min_coverage_rate=0.5),
    )
    assert v.bars == 1  # 교집합은 2024-01-02 하나
    assert v.expected == 3
    assert v.coverage_rate == 0.3333  # 4자리 반올림
    assert v.included is False  # 1/3 < 0.5


def test_empty_reference_calendar_flagged():
    v = evaluate_symbol_coverage(
        symbol="Z", symbol_dates={date(2024, 1, 2)}, calendar_dates=set(), params=PARAMS
    )
    assert v.included is False
    assert "no_reference_calendar" in v.reasons


def test_trading_days_from_df():
    df = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-03"]),
            "close": [1.0, 2.0, 2.0],
        }
    )
    days = trading_days_from_df(df)
    assert days == {date(2024, 1, 2), date(2024, 1, 3)}
    assert trading_days_from_df(pd.DataFrame()) == set()


def test_build_report_lists_every_symbol_with_reasons():
    cal = weekday_calendar(date(2024, 1, 1), date(2024, 3, 1))
    good = evaluate_symbol_coverage(
        symbol="069500", symbol_dates=set(cal), calendar_dates=cal, params=PARAMS
    )
    bad = evaluate_symbol_coverage(
        symbol="BADSYM", symbol_dates=set(sorted(cal)[:3]), calendar_dates=cal, params=PARAMS
    )
    md, payload = build_coverage_report(
        [good, bad],
        params=PARAMS,
        requested_start=date(2024, 1, 1),
        requested_end=date(2024, 3, 1),
        benchmark="069500",
        generated_at=datetime(2024, 3, 2, 9, 0, 0),
    )
    # 제외 종목은 사유와 함께 반드시 표에 존재(무음 누락 금지)
    assert "BADSYM" in md
    assert "insufficient_bars" in md or "low_coverage" in md
    assert payload["summary"] == {"total": 2, "included": 1, "excluded": 1}
    assert payload["included_symbols"] == ["069500"]
    assert {v["symbol"] for v in payload["verdicts"]} == {"069500", "BADSYM"}
