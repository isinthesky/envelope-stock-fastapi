# -*- coding: utf-8 -*-
"""
Paper Trade Bridge (P6) — 라이브 dry-run 시그널 → PaperEvent

golden_cross 엔진의 dry-run 실행 결과(StrategySignalDTO 리스트)를 PaperLedger가
소비할 PaperEvent로 변환한다.

⚠️ 이 브리지는 라이브 15:35 스케줄러에 **자동 배선하지 않는다**. paper 기록 활성화는
운영자의 명시적 결정(설정 플래그 + 전용 실행 경로)을 거쳐야 하며, 이 함수는 그
전환 시 재사용할 순수 변환 계층이다.
"""

from __future__ import annotations

from collections.abc import Iterable

from src.application.domain.paper_trade.ledger import PaperEvent
from src.application.domain.strategy.dto import StrategySignalDTO

_ACTIONS = {"buy", "sell"}


def signals_to_paper_events(signals: Iterable[StrategySignalDTO]) -> list[PaperEvent]:
    """dry-run 시그널을 시간순 PaperEvent로 변환한다(buy/sell만)."""
    events: list[PaperEvent] = []
    for s in signals:
        action = (s.signal_type or "").lower()
        if action not in _ACTIONS:
            continue
        if s.signal_price is None or s.signal_at is None:
            continue
        events.append(
            PaperEvent(
                date=s.signal_at,
                symbol=s.symbol,
                action=action,
                price=s.signal_price,
                reason=s.exit_reason or s.note,
            )
        )
    events.sort(key=lambda e: e.date)
    return events
