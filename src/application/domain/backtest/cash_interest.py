# -*- coding: utf-8 -*-
"""
Idle-cash interest schedule (research opt-in).

포트폴리오 백테스트에서 미투자 현금에 붙는 이자(CD/MMF 등)를 근사한다. 기본 엔진은
현금 이자 0%(기존 동작)이며, 이 스케줄을 명시적으로 넘길 때만 적용된다.

연이율(소수, 0.017 = 1.7%)은 effective_from 이후 다음 구간 전까지 유지된다. 일별
적립은 달력일 기준 복리 ``(1+r)^(Δdays/365) - 1`` 로 계산한다(주말·휴일 포함).

⚠️ 아래 ``APPROX_KRW_CASH_RATE_SCHEDULE``은 **근사 가정치**(CD/MMF 수준)이며 공식 시계열이
아니다. 리포트에 반드시 가정으로 표기한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class CashInterestSchedule:
    """(effective_from, annual_rate) 계단형 연이율 스케줄."""

    steps: tuple[tuple[date, float], ...]
    label: str = "custom"

    def __post_init__(self) -> None:
        if not self.steps:
            raise ValueError("cash interest schedule needs at least one step")
        ordered = tuple(sorted(self.steps, key=lambda s: s[0]))
        if ordered != self.steps:
            object.__setattr__(self, "steps", ordered)
        for _, rate in self.steps:
            if not -0.05 <= rate <= 0.25:
                raise ValueError(f"implausible annual cash rate: {rate}")

    @classmethod
    def flat(cls, annual_rate: float, label: str | None = None) -> "CashInterestSchedule":
        return cls(((date(1900, 1, 1), annual_rate),), label or f"flat_{annual_rate:.2%}")

    def rate_on(self, d: date) -> float:
        rate = 0.0
        for start, r in self.steps:
            if start <= d:
                rate = r
            else:
                break
        return rate

    def accrual_factor(self, prev_day: date, day: date) -> Decimal:
        """prev_day 종가 이후 → day 까지의 이자 증식분(소수). prev_day의 금리를 적용."""
        days = (day - prev_day).days
        if days <= 0:
            return Decimal("0")
        r = self.rate_on(prev_day)
        if r == 0.0:
            return Decimal("0")
        return Decimal(str((1.0 + r) ** (days / 365.0) - 1.0))

    def describe(self) -> str:
        parts = [f"{d.isoformat()}:{r:.2%}" for d, r in self.steps]
        return f"{self.label}(" + ", ".join(parts) + ")"


# 근사 원화 단기금리 가정(CD91/MMF 수준, 연도 평균 근사) — 공식 수치 아님.
APPROX_KRW_CASH_RATE_SCHEDULE = CashInterestSchedule(
    steps=(
        (date(2018, 1, 1), 0.017),
        (date(2020, 1, 1), 0.007),
        (date(2022, 1, 1), 0.025),
        (date(2023, 1, 1), 0.035),
        (date(2025, 1, 1), 0.028),
    ),
    label="approx_krw_cd_mmf",
)
