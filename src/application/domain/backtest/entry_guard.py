# -*- coding: utf-8 -*-
"""
Entry Guard - SafetyGuard 규칙의 백테스트 재현(신규 진입만 차단, 청산은 막지 않음)

라이브 `domain/risk/safety_guard.py`의 기본 한도(`RiskLimitConfigDTO`)를 그대로 쓴다.
라이브와 다른 점: 라이브는 실행마다 빈 통계로 새로 만들어져 아무것도 막지 못한다.
여기서는 "작동하는" 형태로 재현해 수익률 영향을 측정한다.
- 손실 한도는 실현손익이 아니라 일별 시가평가 자산(전일 종가 대비 당일 청산 후 자산) 기준이다.
- 연속 손실은 라이브 TradingDayStats와 같이 일 단위다(당일 연속 손실 청산 수).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True, slots=True)
class EntryGuardConfig:
    daily_loss_limit: float | None = -0.04
    weekly_loss_limit: float | None = -0.07  # 5거래일 전 대비
    monthly_loss_limit: float | None = -0.15  # 21거래일 전 대비
    max_daily_entries: int | None = 3
    max_consecutive_losses_today: int | None = 3
    market_crash_threshold: float | None = -0.02  # 벤치 당일 수익률
    benchmark_returns: dict[date, float] = field(default_factory=dict, compare=False, hash=False)

    def describe(self) -> str:
        parts = []
        for name in (
            "daily_loss_limit",
            "weekly_loss_limit",
            "monthly_loss_limit",
            "max_daily_entries",
            "max_consecutive_losses_today",
            "market_crash_threshold",
        ):
            value = getattr(self, name)
            if value is not None:
                parts.append(f"{name}={value}")
        return "guard(" + ",".join(parts) + ")" if parts else "guard(off)"


@dataclass(slots=True)
class EntryGuardDay:
    """하루 단위 판정 입력."""

    day: date
    equity_now: float  # 당일 청산 반영 후, 신규 진입 전 시가평가 자산
    equity_history: list[float]  # 전일까지의 일별 자산(시가평가)
    entries_today: int
    consecutive_losses_today: int


def check_entry(cfg: EntryGuardConfig, ctx: EntryGuardDay) -> str | None:
    """차단 사유(문자열) 또는 None(허용)."""
    hist = ctx.equity_history

    def _change(lookback: int) -> float | None:
        if len(hist) < lookback or hist[-lookback] <= 0:
            return None
        return ctx.equity_now / hist[-lookback] - 1.0

    if cfg.daily_loss_limit is not None:
        ch = _change(1)
        if ch is not None and ch <= cfg.daily_loss_limit:
            return "guard_daily_loss"
    if cfg.weekly_loss_limit is not None:
        ch = _change(5)
        if ch is not None and ch <= cfg.weekly_loss_limit:
            return "guard_weekly_loss"
    if cfg.monthly_loss_limit is not None:
        ch = _change(21)
        if ch is not None and ch <= cfg.monthly_loss_limit:
            return "guard_monthly_loss"
    if cfg.max_consecutive_losses_today is not None and (
        ctx.consecutive_losses_today >= cfg.max_consecutive_losses_today
    ):
        return "guard_consecutive_losses"
    if cfg.market_crash_threshold is not None:
        bench = cfg.benchmark_returns.get(ctx.day)
        if bench is not None and bench <= cfg.market_crash_threshold:
            return "guard_market_crash"
    if cfg.max_daily_entries is not None and ctx.entries_today >= cfg.max_daily_entries:
        return "guard_max_daily_entries"
    return None
