# -*- coding: utf-8 -*-
"""
Paper Trade Ledger (P6) — 무비용 실시간 추적 회계 (순수 로직)

백테스트 통과 config를 실주문 대신 '기록 전용'으로 운영할 때의 핵심 회계.
라이브 15:35 dry-run 시그널(또는 백테스트 리플레이)을 시간순으로 받아 가상
포지션/거래를 관리하고, 백테스트 OOS와 비교할 요약을 산출한다.

설계 원칙(§10): paper는 **무비용**(수수료/세금/슬리피지 없음) 실시간 추적이다.
비용을 뺀 순수 시그널 성과를 OOS와 대조해 '시그널 자체'의 실현 여부를 본다.

DB/외부 의존 없음 → 완전 단위 테스트 가능. 영속화는 service/repository가 담당.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class PaperConfig:
    initial_capital: Decimal = Decimal("10000000")
    allocation_ratio: float = 0.1  # 신규 포지션당 현금 비율(라이브와 동일)
    max_positions: int = 5


@dataclass(slots=True)
class PaperOpenPosition:
    symbol: str
    quantity: int
    entry_price: Decimal
    entry_date: datetime


@dataclass(frozen=True, slots=True)
class PaperClosedTrade:
    symbol: str
    entry_date: datetime
    entry_price: Decimal
    exit_date: datetime
    exit_price: Decimal
    quantity: int
    profit: Decimal
    profit_rate: float  # %
    holding_days: int
    exit_reason: str | None = None


@dataclass(frozen=True, slots=True)
class PaperSummary:
    initial_capital: Decimal
    cash: Decimal
    positions_value: Decimal
    equity: Decimal
    total_return: float  # %
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    open_positions: int
    closed_trades: int
    win_rate: float  # %
    mdd: float  # %
    daily_sharpe: float
    trades: list[PaperClosedTrade] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PaperEvent:
    """기록할 단일 시그널(라이브 dry-run 또는 리플레이)."""

    date: datetime
    symbol: str
    action: str  # "buy" | "sell"
    price: Decimal
    reason: str | None = None


def _to_date(ts: datetime | date) -> date:
    return ts.date() if isinstance(ts, datetime) else ts


class PaperLedger:
    """무비용 가상 매매 원장."""

    def __init__(self, config: PaperConfig | None = None) -> None:
        self.config = config or PaperConfig()
        self.cash: Decimal = self.config.initial_capital
        self.positions: dict[str, PaperOpenPosition] = {}
        self.closed: list[PaperClosedTrade] = []
        self.realized_pnl: Decimal = Decimal("0")
        # (날짜, equity) 마킹 이력 — MDD/Sharpe용
        self._equity_marks: list[tuple[date, Decimal]] = []

    # ==================== 시그널 기록 ====================

    def record(self, event: PaperEvent) -> str:
        """단일 시그널을 반영한다. 반영 결과 문자열 반환(filled/…/skipped)."""
        if event.action == "buy":
            return self._buy(event)
        if event.action == "sell":
            return self._sell(event)
        return "ignored"

    def record_all(
        self, events: list[PaperEvent], marks: dict[date, dict[str, Decimal]] | None = None
    ) -> None:
        """시간순 시그널을 일괄 반영하고, 날짜별 종가로 MTM 마킹한다."""
        for ev in sorted(events, key=lambda e: e.date):
            self.record(ev)
            if marks is not None:
                d = _to_date(ev.date)
                if d in marks:
                    self.mark_to_market(ev.date, marks[d])

    def _buy(self, ev: PaperEvent) -> str:
        if ev.symbol in self.positions:
            return "skipped:already_held"
        if len(self.positions) >= self.config.max_positions:
            return "skipped:max_positions"
        if ev.price <= 0:
            return "skipped:invalid_price"
        target = self.cash * Decimal(str(self.config.allocation_ratio))
        qty = int(target / ev.price)
        if qty < 1 or self.cash < ev.price * qty:
            return "skipped:insufficient_cash"
        self.cash -= ev.price * qty
        self.positions[ev.symbol] = PaperOpenPosition(ev.symbol, qty, ev.price, ev.date)
        return "filled:buy"

    def _sell(self, ev: PaperEvent) -> str:
        pos = self.positions.get(ev.symbol)
        if pos is None:
            return "skipped:no_position"
        proceeds = ev.price * pos.quantity
        cost = pos.entry_price * pos.quantity
        profit = proceeds - cost
        self.cash += proceeds
        self.realized_pnl += profit
        rate = float(profit / cost * 100) if cost > 0 else 0.0
        self.closed.append(
            PaperClosedTrade(
                symbol=ev.symbol,
                entry_date=pos.entry_date,
                entry_price=pos.entry_price,
                exit_date=ev.date,
                exit_price=ev.price,
                quantity=pos.quantity,
                profit=profit,
                profit_rate=round(rate, 4),
                holding_days=(_to_date(ev.date) - _to_date(pos.entry_date)).days,
                exit_reason=ev.reason,
            )
        )
        del self.positions[ev.symbol]
        return "filled:sell"

    # ==================== 시가평가 ====================

    def mark_to_market(self, when: datetime | date, prices: dict[str, Decimal]) -> Decimal:
        """보유 포지션을 종가로 평가하고 equity를 기록한다. equity 반환."""
        pos_val = self._positions_value(prices)
        equity = self.cash + pos_val
        self._equity_marks.append((_to_date(when), equity))
        return equity

    def _positions_value(self, prices: dict[str, Decimal]) -> Decimal:
        total = Decimal("0")
        for symbol, pos in self.positions.items():
            px = prices.get(symbol, pos.entry_price)
            total += px * pos.quantity
        return total

    # ==================== 요약 ====================

    def summary(self, as_of_prices: dict[str, Decimal] | None = None) -> PaperSummary:
        prices = as_of_prices or {}
        pos_val = self._positions_value(prices)
        equity = self.cash + pos_val
        c0 = self.config.initial_capital
        total_return = float((equity - c0) / c0 * 100) if c0 > 0 else 0.0
        unrealized = Decimal("0")
        for symbol, pos in self.positions.items():
            px = prices.get(symbol, pos.entry_price)
            unrealized += (px - pos.entry_price) * pos.quantity
        wins = sum(1 for t in self.closed if t.profit > 0)
        win_rate = round(wins / len(self.closed) * 100, 2) if self.closed else 0.0
        return PaperSummary(
            initial_capital=c0,
            cash=self.cash,
            positions_value=pos_val,
            equity=equity,
            total_return=round(total_return, 4),
            realized_pnl=self.realized_pnl,
            unrealized_pnl=unrealized,
            open_positions=len(self.positions),
            closed_trades=len(self.closed),
            win_rate=win_rate,
            mdd=self._mdd(),
            daily_sharpe=self._daily_sharpe(),
            trades=list(self.closed),
        )

    def _mdd(self) -> float:
        if len(self._equity_marks) < 2:
            return 0.0
        peak = self._equity_marks[0][1]
        mdd = Decimal("0")
        for _, eq in self._equity_marks:
            if eq > peak:
                peak = eq
            if peak > 0:
                dd = (eq - peak) / peak
                if dd < mdd:
                    mdd = dd
        return round(float(mdd * 100), 2)

    def _daily_sharpe(self) -> float:
        if len(self._equity_marks) < 3:
            return 0.0
        eq = [float(e) for _, e in self._equity_marks]
        rets = [eq[i] / eq[i - 1] - 1.0 for i in range(1, len(eq)) if eq[i - 1] > 0]
        if len(rets) < 2:
            return 0.0
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        sd = var**0.5
        return round(mean / sd, 4) if sd > 0 else 0.0
