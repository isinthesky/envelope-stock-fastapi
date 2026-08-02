# -*- coding: utf-8 -*-
"""
OHLCV Coverage Gate - 백테스트 유니버스 데이터 품질 게이트 (P1)

목적:
    walk-forward 검증에 투입하기 전, 각 종목의 일봉 데이터가 충분/온전한지
    **하드 게이트**로 판정한다. 감사에서 지적된 "삼성 30일/0거래" 같은 무음
    누락(silent skip)을 방지하기 위해, 제외된 종목도 반드시 사유와 함께 리포트에
    남긴다.

커버리지 분모:
    한국 시장은 공휴일이 연 4~6%(평일 기준)이므로 "평일 수"를 분모로 쓰면 100%가
    구조적으로 불가능하다. 따라서 분모는 **기준 종목(벤치마크, 예: KODEX 200)의
    실제 거래일 집합**을 사용한다. 즉 "벤치마크가 거래된 날 중 이 종목도 데이터가
    있는 비율"을 커버리지로 정의한다. 벤치마크 달력이 없으면 평일 기준으로
    폴백하되, 그 경우 임계값을 낮게 잡아야 한다(호출측 책임).

이 모듈은 순수 로직만 포함한다(DB/API 의존 없음 → 단위 테스트 가능).
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pandas as pd


@dataclass(frozen=True, slots=True)
class CoverageParams:
    """게이트 임계값."""

    min_bars: int  # 최소 거래일 수(예: long_period + test 창). 미만이면 제외.
    min_coverage_rate: float  # 최소 커버리지(예: 0.98). 미만이면 제외.


@dataclass(frozen=True, slots=True)
class CoverageVerdict:
    symbol: str
    included: bool
    bars: int
    expected: int
    coverage_rate: float
    actual_start: date | None
    actual_end: date | None
    reasons: tuple[str, ...]


def trading_days_from_df(df: pd.DataFrame) -> set[date]:
    """OHLCV DataFrame의 timestamp 컬럼에서 거래일(date) 집합을 추출한다."""
    if df is None or df.empty or "timestamp" not in df.columns:
        return set()
    ts = pd.to_datetime(df["timestamp"])
    return {t.date() for t in ts}


def weekday_calendar(start: date, end: date) -> set[date]:
    """폴백용 평일 달력(월~금). 벤치마크 달력이 없을 때만 사용."""
    days: set[date] = set()
    cur = start
    while cur <= end:
        if cur.weekday() < 5:
            days.add(cur)
        cur += timedelta(days=1)
    return days


def evaluate_symbol_coverage(
    *,
    symbol: str,
    symbol_dates: set[date],
    calendar_dates: set[date],
    params: CoverageParams,
) -> CoverageVerdict:
    """단일 종목의 커버리지를 판정한다.

    Args:
        symbol_dates: 이 종목이 데이터를 가진 거래일 집합
        calendar_dates: 기준 거래일 집합(벤치마크 달력). 이 안에 든 날만 분모/분자로 계산.
    """
    covered = symbol_dates & calendar_dates
    bars = len(covered)
    expected = len(calendar_dates)
    coverage_rate = (bars / expected) if expected else 0.0

    reasons: list[str] = []
    if expected == 0:
        reasons.append("no_reference_calendar")
    if bars < params.min_bars:
        reasons.append(f"insufficient_bars(bars={bars}<min={params.min_bars})")
    if expected > 0 and coverage_rate < params.min_coverage_rate:
        reasons.append(f"low_coverage(rate={coverage_rate:.4f}<min={params.min_coverage_rate})")

    actual_start = min(symbol_dates) if symbol_dates else None
    actual_end = max(symbol_dates) if symbol_dates else None

    return CoverageVerdict(
        symbol=symbol,
        included=not reasons,
        bars=bars,
        expected=expected,
        coverage_rate=round(coverage_rate, 4),
        actual_start=actual_start,
        actual_end=actual_end,
        reasons=tuple(reasons),
    )


def build_coverage_report(
    verdicts: list[CoverageVerdict],
    *,
    params: CoverageParams,
    requested_start: date,
    requested_end: date,
    benchmark: str | None,
    generated_at: datetime,
) -> tuple[str, dict]:
    """포함/제외 종목을 사유와 함께 정리한 (markdown, json) 리포트를 만든다.

    무음 누락 금지: 모든 종목이 사유와 함께 표에 남는다.
    """
    included = [v for v in verdicts if v.included]
    excluded = [v for v in verdicts if not v.included]

    lines: list[str] = [
        "# OHLCV Coverage Gate Report",
        "",
        f"- Generated: `{generated_at.isoformat(timespec='seconds')}`",
        f"- Requested window: `{requested_start}` ~ `{requested_end}`",
        f"- Reference calendar (benchmark): `{benchmark}`",
        f"- Gate: min_bars=`{params.min_bars}`, min_coverage=`{params.min_coverage_rate}`",
        f"- Result: **{len(included)} included / {len(excluded)} excluded** "
        f"(total {len(verdicts)})",
        "",
        "## Excluded (사유 포함 — 무음 누락 금지)",
        "",
        "| Symbol | Bars | Coverage | Start | End | Reasons |",
        "| --- | ---: | ---: | --- | --- | --- |",
    ]
    for v in sorted(excluded, key=lambda x: x.symbol):
        lines.append(
            f"| `{v.symbol}` | {v.bars} | {v.coverage_rate:.2%} | "
            f"{v.actual_start or '-'} | {v.actual_end or '-'} | {'; '.join(v.reasons)} |"
        )
    if not excluded:
        lines.append("| _(none)_ | | | | | |")

    lines.extend(
        [
            "",
            "## Included",
            "",
            "| Symbol | Bars | Coverage | Start | End |",
            "| --- | ---: | ---: | --- | --- |",
        ]
    )
    for v in sorted(included, key=lambda x: x.symbol):
        lines.append(
            f"| `{v.symbol}` | {v.bars} | {v.coverage_rate:.2%} | "
            f"{v.actual_start or '-'} | {v.actual_end or '-'} |"
        )
    if not included:
        lines.append("| _(none)_ | | | | |")

    markdown = "\n".join(lines) + "\n"

    payload = {
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "requested_start": requested_start.isoformat(),
        "requested_end": requested_end.isoformat(),
        "benchmark": benchmark,
        "gate": {
            "min_bars": params.min_bars,
            "min_coverage_rate": params.min_coverage_rate,
        },
        "summary": {
            "total": len(verdicts),
            "included": len(included),
            "excluded": len(excluded),
        },
        "included_symbols": [v.symbol for v in sorted(included, key=lambda x: x.symbol)],
        "verdicts": [
            {
                "symbol": v.symbol,
                "included": v.included,
                "bars": v.bars,
                "expected": v.expected,
                "coverage_rate": v.coverage_rate,
                "actual_start": v.actual_start.isoformat() if v.actual_start else None,
                "actual_end": v.actual_end.isoformat() if v.actual_end else None,
                "reasons": list(v.reasons),
            }
            for v in sorted(verdicts, key=lambda x: x.symbol)
        ],
    }
    return markdown, payload
