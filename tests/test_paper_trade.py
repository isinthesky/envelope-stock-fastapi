# -*- coding: utf-8 -*-
"""P6 paper-trade 브리지 테스트 — ledger / reconcile / bridge (순수 로직)."""

from datetime import datetime
from decimal import Decimal

from src.application.domain.paper_trade.bridge import signals_to_paper_events
from src.application.domain.paper_trade.ledger import (
    PaperConfig,
    PaperEvent,
    PaperLedger,
)
from src.application.domain.paper_trade.reconcile import reconcile_paper_vs_oos
from src.application.domain.strategy.dto import StrategySignalDTO

CAP = PaperConfig(initial_capital=Decimal("10000000"), allocation_ratio=0.1, max_positions=2)


def _ev(day, symbol, action, price, reason=None):
    return PaperEvent(datetime(2024, 1, day), symbol, action, Decimal(str(price)), reason)


# ==================== Ledger ====================


def test_buy_then_sell_realizes_pnl():
    led = PaperLedger(CAP)
    assert led.record(_ev(2, "A", "buy", 100)) == "filled:buy"
    # 10% of 10M = 1M / 100 = 10000주
    assert led.positions["A"].quantity == 10000
    assert led.record(_ev(10, "A", "sell", 110, "take_profit")) == "filled:sell"
    s = led.summary()
    assert s.closed_trades == 1
    assert s.realized_pnl == Decimal("100000")  # (110-100)*10000
    assert s.trades[0].profit_rate == 10.0
    assert s.trades[0].exit_reason == "take_profit"
    assert s.win_rate == 100.0


def test_max_positions_and_already_held_skip():
    led = PaperLedger(CAP)  # max 2
    led.record(_ev(2, "A", "buy", 100))
    led.record(_ev(2, "B", "buy", 100))
    assert led.record(_ev(2, "C", "buy", 100)) == "skipped:max_positions"
    assert led.record(_ev(3, "A", "buy", 100)) == "skipped:already_held"


def test_sell_without_position_skipped():
    led = PaperLedger(CAP)
    assert led.record(_ev(2, "Z", "sell", 100)) == "skipped:no_position"


def test_mark_to_market_and_unrealized():
    led = PaperLedger(CAP)
    led.record(_ev(2, "A", "buy", 100))
    led.mark_to_market(datetime(2024, 1, 3), {"A": Decimal("120")})
    s = led.summary({"A": Decimal("120")})
    assert s.unrealized_pnl == Decimal("200000")  # (120-100)*10000
    assert s.equity == s.cash + s.positions_value
    assert s.open_positions == 1


def test_mdd_and_sharpe_from_marks():
    led = PaperLedger(CAP)
    led.record(_ev(2, "A", "buy", 100))
    for day, px in [(3, 110), (4, 90), (5, 130)]:  # 상승→하락(낙폭)→반등
        led.mark_to_market(datetime(2024, 1, day), {"A": Decimal(str(px))})
    s = led.summary({"A": Decimal("130")})
    assert s.mdd < 0  # 낙폭 발생
    assert isinstance(s.daily_sharpe, float)


# ==================== Reconcile ====================


def _summary_with(sharpe: float, closed: int, win: float = 60.0):
    from src.application.domain.paper_trade.ledger import PaperSummary

    return PaperSummary(
        initial_capital=Decimal("10000000"),
        cash=Decimal("10500000"),
        positions_value=Decimal("0"),
        equity=Decimal("10500000"),
        total_return=5.0,
        realized_pnl=Decimal("500000"),
        unrealized_pnl=Decimal("0"),
        open_positions=0,
        closed_trades=closed,
        win_rate=win,
        mdd=-8.0,
        daily_sharpe=sharpe,
        trades=[],
    )


def test_reconcile_within_tolerance_recommends_small_live():
    r = reconcile_paper_vs_oos(_summary_with(0.10, 30), oos_daily_sharpe=0.12)
    assert r.min_closed_trades_met is True
    assert r.within_tolerance is True
    assert "소액" in r.recommendation


def test_reconcile_insufficient_trades_blocks():
    r = reconcile_paper_vs_oos(_summary_with(0.20, 5), oos_daily_sharpe=0.12)
    assert r.min_closed_trades_met is False
    assert r.within_tolerance is False
    assert "표본 부족" in r.recommendation


def test_reconcile_large_shortfall_blocks():
    r = reconcile_paper_vs_oos(
        _summary_with(-0.60, 40), oos_daily_sharpe=0.12, max_sharpe_shortfall=0.5
    )
    assert r.within_tolerance is False
    assert "실전 금지" in r.recommendation


# ==================== Bridge ====================


def _sig(sid, symbol, stype, price, day, reason=None):
    return StrategySignalDTO(
        id=sid,
        strategy_id=1,
        symbol=symbol,
        signal_type=stype,
        signal_status="skipped",
        signal_price=Decimal(str(price)),
        signal_at=datetime(2024, 1, day),
        exit_reason=reason,
    )


def test_bridge_maps_buy_sell_sorted_and_filters_hold():
    signals = [
        _sig(2, "A", "sell", 110, 10, "take_profit"),
        _sig(1, "A", "buy", 100, 2),
        _sig(3, "B", "hold", 50, 3),  # 무시
    ]
    events = signals_to_paper_events(signals)
    assert [e.action for e in events] == ["buy", "sell"]  # 시간순 정렬
    assert events[0].symbol == "A" and events[0].price == Decimal("100")
    assert events[1].reason == "take_profit"


def test_bridge_end_to_end_into_ledger():
    signals = [
        _sig(1, "A", "buy", 100, 2),
        _sig(2, "A", "sell", 120, 15, "take_profit"),
    ]
    led = PaperLedger(CAP)
    for ev in signals_to_paper_events(signals):
        led.record(ev)
    s = led.summary()
    assert s.closed_trades == 1
    assert s.realized_pnl == Decimal("200000")  # (120-100)*10000
