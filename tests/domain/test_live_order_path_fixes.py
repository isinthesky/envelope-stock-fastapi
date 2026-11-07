"""실주문 경로 결함 수정 회귀 테스트 (2026-11-06).

1) 계좌 잔고: TTTC8908R 응답에서 TTTC8434R 전용 필드를 읽어 전부 0이던 버그
2) 15:35 정규장 지정가(장 마감 뒤) → 장후 시간외 종가(ORD_DVSN 06)
3) 접수 직후 신호가로 EXECUTED 기록 → PENDING + 체결 대사(reconcile)로 확정
4) 실주문 엔진에 시장 국면 게이트 부재
5) 체결조회(inquire-daily-ccld)를 POST로 호출하던 버그
"""

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from src.adapters.database.models.strategy_signal import SignalStatus, SignalType
from src.adapters.database.models.strategy_symbol_state import SymbolState
from src.application.common.exceptions import OrderError
from src.application.domain.account.service import AccountService
from src.application.domain.order.dto import OrderCreateRequestDTO
from src.application.domain.order.service import OrderService, resolve_ord_dvsn
from src.application.domain.strategy import golden_cross_engine as engine_module
from src.application.domain.strategy.golden_cross_engine import (
    KST,
    GoldenCrossEngine,
    _order_session_closed,
    estimate_realized_pnl,
)
from src.application.domain.strategy.market_regime import market_regime_ok
from src.application.domain.strategy.state_machine import Signal, StateTransition

# ==================== 1) 계좌 잔고 ====================


@pytest.mark.asyncio
async def test_account_balance_reads_inquire_balance_summary_and_orderable_cash() -> None:
    kis = MagicMock()

    async def fake_get(path, params=None, headers=None):
        if path.endswith("inquire-balance"):
            assert headers["tr_id"].endswith("8434R")
            return {
                "output1": [
                    {"pdno": "069500", "hldg_qty": "10"},
                    {"pdno": "000000", "hldg_qty": "0"},  # 당일 전량 매도 잔존 행
                ],
                "output2": [
                    {
                        "tot_evlu_amt": "10500000",
                        "prvs_rcdl_excc_amt": "9500000",
                        "scts_evlu_amt": "1000000",
                        "pchs_amt_smtl_amt": "800000",
                        "evlu_pfls_smtl_amt": "200000",
                    }
                ],
            }
        assert headers["tr_id"].endswith("8908R")
        return {"output": {"ord_psbl_cash": "9400000"}}

    kis.get = AsyncMock(side_effect=fake_get)
    service = AccountService(kis, SimpleNamespace())

    balance = await service.get_account_balance("12345678", use_cache=False)

    assert balance.total_balance == Decimal("10500000")
    assert balance.cash_balance == Decimal("9500000")
    assert balance.stock_balance == Decimal("1000000")
    assert balance.available_amount == Decimal("9400000")
    assert balance.total_profit_loss == Decimal("200000")
    assert balance.total_profit_loss_rate == Decimal("25.00")
    assert balance.position_count == 1  # 이전: pchs_amt_smtl_amt(금액)를 종목 수로 사용


# ==================== 2) 주문 구분 ====================


def test_closing_price_type_maps_to_after_hours_close_and_unknown_is_rejected() -> None:
    assert resolve_ord_dvsn("closing") == "06"
    assert resolve_ord_dvsn("limit") == "00"
    assert resolve_ord_dvsn("market") == "01"
    with pytest.raises(OrderError):
        resolve_ord_dvsn("stop")  # 이전: 미지 유형을 조용히 지정가(00)로 폴백


def test_closing_order_request_accepts_zero_price() -> None:
    dto = OrderCreateRequestDTO(
        symbol="069500", order_type="buy", price_type="closing", price=Decimal("0"), quantity=1
    )
    assert dto.price_type == "closing"


@pytest.mark.asyncio
async def test_update_order_status_uses_get_for_daily_ccld() -> None:
    kis = MagicMock()
    kis.get = AsyncMock(
        return_value={
            "output1": [{"odno": "0001", "tot_ccld_qty": "3", "avg_prvs": "35000", "ord_qty": "3"}]
        }
    )
    kis.post = AsyncMock(side_effect=AssertionError("inquire-daily-ccld is a GET API"))
    order = SimpleNamespace(
        id=1,
        order_id="91252+0001",
        account_no="12345678",
        symbol="069500",
        order_time=datetime(2026, 11, 6, 15, 35),
        order_quantity=3,
        filled_quantity=0,
        remaining_quantity=3,
        filled_avg_price=Decimal("0"),
        filled_time=None,
        status="submitted",
    )
    updated = SimpleNamespace(**{**order.__dict__, "filled_quantity": 3, "status": "filled"})
    repo = SimpleNamespace(
        get_by_order_id=AsyncMock(side_effect=[order, updated]), update_by_id=AsyncMock()
    )
    service = OrderService(kis, session=None)

    import src.application.domain.order.service as order_module

    original = order_module.OrderRepository
    order_module.OrderRepository = lambda session: repo  # type: ignore[assignment]
    try:
        status = await OrderService.update_order_status.__wrapped__(
            service, object(), order.order_id
        )
    finally:
        order_module.OrderRepository = original  # type: ignore[assignment]

    assert status.filled_quantity == 3
    kis.get.assert_awaited_once()


# ==================== 3) 접수 → PENDING, 대사로 확정 ====================


class _Signals:
    def __init__(self, pending=()) -> None:
        self.updates: list[tuple[int, dict]] = []
        self.pending = list(pending)

    async def update_execution(self, signal_id, **kwargs):
        self.updates.append((signal_id, kwargs))

    async def get_pending_signals(self, strategy_id):
        _ = strategy_id
        return self.pending


class _States:
    def __init__(self, state=None) -> None:
        self.state = state
        self.calls: list[tuple[str, dict]] = []

    async def get_by_strategy_and_symbol(self, strategy_id, symbol):
        _ = strategy_id, symbol
        return self.state

    async def update_state(self, **kwargs):
        self.calls.append(("update_state", kwargs))

    async def reset_to_waiting(self, *args):
        self.calls.append(("reset_to_waiting", {"args": args}))


def _engine(signals=None, states=None) -> GoldenCrossEngine:
    session = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    engine = GoldenCrossEngine(session=session, kis_client=SimpleNamespace())
    engine.signal_repo = signals or _Signals()
    engine.symbol_state_repo = states or _States()
    return engine


@pytest.mark.asyncio
async def test_place_order_submits_closing_order_and_leaves_signal_pending(monkeypatch) -> None:
    captured: dict = {}

    class FakeOrderService:
        def __init__(self, *args, **kwargs):
            pass

        async def create_order(self, session, request):
            captured["request"] = request
            return SimpleNamespace(order_no="0001", order_id="91252+0001")

    monkeypatch.setattr(engine_module, "OrderService", FakeOrderService)
    monkeypatch.setattr(engine_module.settings, "strategy_order_price_type", "closing")
    signals = _Signals()
    engine = _engine(signals)

    await engine._place_order(
        SimpleNamespace(account_no="12345678"),
        "069500",
        "buy",
        Decimal("35000"),
        3,
        SimpleNamespace(id=7),
        metadata={},
    )

    request = captured["request"]
    assert request.price_type == "closing" and request.price == Decimal("0")
    signal_id, kwargs = signals.updates[-1]
    assert signal_id == 7
    assert kwargs["status"] == SignalStatus.PENDING  # 이전: 접수 즉시 EXECUTED(신호가)
    assert kwargs["order_no"] == "0001" and kwargs["target_quantity"] == 3
    assert kwargs["metadata"]["broker_order_id"] == "91252+0001"


def _pending_signal(signal_type, signal_at=None, target=3, meta=None):
    return SimpleNamespace(
        id=11,
        symbol="069500",
        signal_type=signal_type.value,
        order_no="0001",
        target_quantity=target,
        signal_at=signal_at or datetime.now(KST),
        metadata_json=json.dumps({"broker_order_id": "91252+0001", **(meta or {})}),
    )


def _patch_order_status(monkeypatch, filled_qty: int, avg: str = "35100") -> None:
    class FakeOrderService:
        def __init__(self, *args, **kwargs):
            pass

        async def update_order_status(self, session, order_id):
            assert order_id == "91252+0001"
            return SimpleNamespace(filled_quantity=filled_qty, filled_avg_price=Decimal(avg))

    monkeypatch.setattr(engine_module, "OrderService", FakeOrderService)


@pytest.mark.asyncio
async def test_reconcile_confirms_buy_fill_with_actual_price(monkeypatch) -> None:
    _patch_order_status(monkeypatch, filled_qty=3)
    signals = _Signals([_pending_signal(SignalType.BUY)])
    states = _States(SimpleNamespace(state=SymbolState.IN_POSITION.value))
    engine = _engine(signals, states)

    summary = await engine.reconcile_open_orders(1)

    assert summary["executed"] == 1
    _, kwargs = signals.updates[-1]
    assert kwargs["status"] == SignalStatus.EXECUTED
    assert kwargs["executed_price"] == Decimal("35100") and kwargs["executed_quantity"] == 3
    assert states.calls[0][1]["entry_price"] == Decimal("35100")


@pytest.mark.asyncio
async def test_reconcile_keeps_open_order_during_session(monkeypatch) -> None:
    _patch_order_status(monkeypatch, filled_qty=0)
    today_kst = datetime.now(KST)
    signals = _Signals([_pending_signal(SignalType.BUY, signal_at=today_kst)])
    engine = _engine(signals)
    monkeypatch.setattr(engine_module, "_order_session_closed", lambda *a: False)

    summary = await engine.reconcile_open_orders(1)

    assert summary["open"] == 1 and signals.updates == []


@pytest.mark.asyncio
async def test_reconcile_cancels_unfilled_buy_after_session_and_resets_state(monkeypatch) -> None:
    _patch_order_status(monkeypatch, filled_qty=0)
    yesterday = datetime.now(KST) - timedelta(days=1)
    signals = _Signals([_pending_signal(SignalType.BUY, signal_at=yesterday)])
    states = _States()
    engine = _engine(signals, states)

    summary = await engine.reconcile_open_orders(1)

    assert summary["cancelled"] == 1
    assert signals.updates[-1][1]["status"] == SignalStatus.CANCELLED
    assert states.calls == [("reset_to_waiting", {"args": (1, "069500")})]


@pytest.mark.asyncio
async def test_reconcile_sell_records_cost_aware_pnl_and_restores_partial(monkeypatch) -> None:
    _patch_order_status(monkeypatch, filled_qty=2, avg="11000")
    signals = _Signals([_pending_signal(SignalType.SELL, target=3, meta={"entry_price": "10000"})])
    states = _States()
    engine = _engine(signals, states)
    engine._get_account_service = AsyncMock(
        return_value=SimpleNamespace(
            get_position_list=AsyncMock(
                return_value=SimpleNamespace(
                    positions=[
                        SimpleNamespace(
                            symbol="069500", quantity=1, avg_purchase_price=Decimal("10000")
                        )
                    ]
                )
            )
        )
    )

    await engine.reconcile_open_orders(1)

    _, kwargs = signals.updates[-1]
    gross = Decimal("2000")  # (11000-10000) * 2
    assert kwargs["status"] == SignalStatus.EXECUTED and kwargs["executed_quantity"] == 2
    assert kwargs["realized_pnl"] < gross  # 수수료·세금 차감
    # 잔량 1주 재매도를 위해 IN_POSITION 복원(진입가 보존)
    assert states.calls[-1] == (
        "update_state",
        {
            "strategy_id": 1,
            "symbol": "069500",
            "new_state": SymbolState.IN_POSITION,
            "entry_price": Decimal("10000"),
        },
    )


def test_estimate_realized_pnl_subtracts_round_trip_costs() -> None:
    pnl, ratio = estimate_realized_pnl(Decimal("10000"), Decimal("11000"), 10, "069500")
    assert pnl < Decimal("10000")
    assert Decimal("0.09") < ratio < Decimal("0.1")


def test_order_session_closed_boundaries() -> None:
    placed = datetime(2026, 11, 6, 6, 35, tzinfo=timezone.utc)  # 15:35 KST
    assert not _order_session_closed(placed, datetime(2026, 11, 6, 15, 50, tzinfo=KST))
    assert _order_session_closed(placed, datetime(2026, 11, 6, 16, 6, tzinfo=KST))
    assert _order_session_closed(placed, datetime(2026, 11, 9, 9, 0, tzinfo=KST))


# ==================== 중복 가드 ====================


class _History:
    def __init__(self, latest) -> None:
        self.latest = latest

    async def get_by_symbol(self, strategy_id, symbol, limit=1):
        _ = strategy_id, symbol, limit
        return [self.latest]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "signal_type", "target", "executed", "blocked"),
    [
        (SignalStatus.PENDING.value, SignalType.BUY, 3, None, True),  # 체결 대기
        (SignalStatus.FAILED.value, SignalType.BUY, 3, None, True),  # 마킹 실패
        (SignalStatus.CANCELLED.value, SignalType.BUY, 3, None, False),  # 미체결 확정 → 재시도
        (SignalStatus.EXECUTED.value, SignalType.BUY, 3, 3, True),
        (SignalStatus.EXECUTED.value, SignalType.SELL, 3, 2, False),  # 일부 체결 잔량
        (SignalStatus.EXECUTED.value, SignalType.SELL, 3, 3, True),
    ],
)
async def test_duplicate_guard_matrix(status, signal_type, target, executed, blocked) -> None:
    latest = SimpleNamespace(
        id=5,
        signal_type=signal_type.value,
        signal_status=status,
        prev_state="a",
        new_state="b",
        order_no="0001",
        target_quantity=target,
        executed_quantity=executed,
    )
    engine = _engine()
    engine.signal_repo = _History(latest)

    found = await engine._find_duplicate_executed_signal(1, "069500", signal_type, "a", "b")

    assert (found is not None) is blocked


# ==================== 4) 시장 국면 게이트 ====================


def test_market_regime_fail_closed_for_live_and_open_for_scan() -> None:
    assert market_regime_ok(None, fail_open=True) is True
    assert market_regime_ok(None, fail_open=False) is False
    stale = pd.DataFrame(
        {
            "timestamp": [pd.Timestamp("2020-01-01", tz="UTC")],
            "high": [1.0],
            "low": [1.0],
            "close": [1.0],
        }
    )
    assert market_regime_ok(stale, fail_open=False) is False


@pytest.mark.asyncio
async def test_live_buy_is_blocked_by_regime_gate_and_state_reset() -> None:
    created = SimpleNamespace(
        id=21, signal_type=SignalType.BUY.value, signal_status=SignalStatus.PENDING.value
    )

    class Signals(_Signals):
        async def get_by_symbol(self, *a, **k):
            return []

        async def create_signal(self, **kwargs):
            return created

    signals = Signals()
    states = _States()
    engine = _engine(signals, states)
    engine._execute_buy = AsyncMock(side_effect=AssertionError("regime block must not order"))
    engine._model_to_dto = lambda model: model

    await engine._handle_signal(
        strategy=SimpleNamespace(id=1, account_no="12345678"),
        symbol="069500",
        transition=StateTransition(
            new_state=SymbolState.IN_POSITION, signal=Signal.BUY, reason="gc"
        ),
        current_snapshot=SimpleNamespace(
            close=Decimal("100"), ma_short=1, ma_long=1, stoch_k=1.0, stoch_d=1.0
        ),
        state=SimpleNamespace(state=SymbolState.READY_TO_BUY.value),
        config=SimpleNamespace(),
        safety_guard=SimpleNamespace(),
        dry_run=False,
        entry_regime_allowed=False,
    )

    assert signals.updates[-1][1] == {"status": SignalStatus.SKIPPED, "exit_reason": "regime_block"}
    assert states.calls == [("reset_to_waiting", {"args": (1, "069500")})]


def test_regime_adx_handles_flat_bars_and_decimal_inputs() -> None:
    """di_sum == 0(보합 봉)과 DB Decimal 입력에서도 예외 없이 판정한다(이전: 항상 예외 → fail-open)."""
    from src.application.domain.backtest.regime_filter import (
        RegimeEntryFilter,
        compute_allowed_entry_dates,
    )

    n = 120
    flat = [Decimal("100")] * 30  # 보합 구간 → +DM=-DM=0 → di_sum 0
    trend = [Decimal(str(100 + i)) for i in range(n - 30)]
    closes = flat + trend
    df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=n, freq="D", tz="UTC"),
            "high": [c + 1 if i >= 30 else c for i, c in enumerate(closes)],
            "low": [c - 1 if i >= 30 else c for i, c in enumerate(closes)],
            "close": closes,
        }
    ).astype({"high": object, "low": object, "close": object})

    allowed = compute_allowed_entry_dates(df, RegimeEntryFilter(use_adx=True, adx_min=20.0))

    assert allowed is not None
    assert df["timestamp"].iloc[-1].date() in allowed  # 강한 상승 추세 → 허용


def test_ma_drift_between_scan_settings_and_strategy_config_is_logged(monkeypatch, caplog) -> None:
    from src.application.domain.strategy.dto import GoldenCrossConfigDTO, GoldenCrossMAConfig

    monkeypatch.setattr(engine_module.settings, "gc_short_ma_period", 50)
    monkeypatch.setattr(engine_module.settings, "gc_long_ma_period", 200)
    config = GoldenCrossConfigDTO(ma_config=GoldenCrossMAConfig(short_period=55, long_period=165))

    with caplog.at_level("ERROR"):
        engine_module._warn_if_ma_drift(1, config)

    assert "MA drift" in caplog.text


def test_default_scan_ma_matches_default_strategy_config() -> None:
    from src.application.domain.strategy.dto import GoldenCrossConfigDTO
    from src.settings.config import Settings

    defaults = GoldenCrossConfigDTO().ma_config
    fields = Settings.model_fields
    assert (fields["gc_short_ma_period"].default, fields["gc_long_ma_period"].default) == (
        defaults.short_period,
        defaults.long_period,
    )


# ==================== SafetyGuard 연결(2026-11-07) ====================


def test_safety_guard_market_crash_and_daily_entry_cap() -> None:
    from src.application.domain.risk.safety_guard import SafetyGuard

    guard = SafetyGuard(initial_capital=Decimal("10000000"))
    assert guard.can_trade()[0] is True
    guard.update_market_change(-0.021)
    assert guard.can_trade()[0] is False  # 시장 급락 → 신규 매수 차단
    assert guard.can_trade(is_risk_reducing=True)[0] is True  # 매도는 허용
    guard.update_market_change(0.0)
    for sym in ("A", "B", "C"):
        guard.record_entry(sym)
    allowed, reason, _ = guard.can_trade()
    assert allowed is False and reason is not None  # 일 신규 진입 3건 상한


@pytest.mark.asyncio
async def test_live_buy_blocked_at_max_positions_and_state_reset() -> None:
    created = SimpleNamespace(
        id=31, signal_type=SignalType.BUY.value, signal_status=SignalStatus.PENDING.value
    )

    class Signals(_Signals):
        async def get_by_symbol(self, *a, **k):
            return []

        async def create_signal(self, **kwargs):
            return created

    signals, states = Signals(), _States()
    engine = _engine(signals, states)
    engine._run_state = {"held": 5, "max_positions": 5}
    engine._execute_buy = AsyncMock(side_effect=AssertionError("max positions must block"))
    engine._model_to_dto = lambda model: model

    await engine._handle_signal(
        strategy=SimpleNamespace(id=1, account_no="12345678"),
        symbol="069500",
        transition=StateTransition(
            new_state=SymbolState.IN_POSITION, signal=Signal.BUY, reason="gc"
        ),
        current_snapshot=SimpleNamespace(
            close=Decimal("100"), ma_short=1, ma_long=1, stoch_k=1.0, stoch_d=1.0
        ),
        state=SimpleNamespace(state=SymbolState.READY_TO_BUY.value),
        config=SimpleNamespace(),
        safety_guard=SimpleNamespace(),
        dry_run=False,
    )

    assert signals.updates[-1][1] == {
        "status": SignalStatus.SKIPPED,
        "exit_reason": "max_positions",
    }
    assert states.calls == [("reset_to_waiting", {"args": (1, "069500")})]


@pytest.mark.asyncio
async def test_benchmark_change_uses_today_bar_only(monkeypatch) -> None:
    engine = _engine()
    today = pd.Timestamp(datetime.now(KST).date())
    fresh = pd.DataFrame(
        {"timestamp": [today - pd.Timedelta(days=1), today], "close": [100.0, 97.0]}
    )
    engine._fetch_ohlcv = AsyncMock(return_value=fresh)
    assert await engine._benchmark_change_today() == pytest.approx(-0.03)
    stale = fresh.assign(timestamp=fresh["timestamp"] - pd.Timedelta(days=3))
    engine._fetch_ohlcv = AsyncMock(return_value=stale)
    assert await engine._benchmark_change_today() == 0.0  # 당일 봉 없음 → 급락 판정 안 함


@pytest.mark.asyncio
async def test_engine_fetch_forces_same_day_bar() -> None:
    engine = _engine()
    seen = {}

    class Loader:
        async def load_ohlcv_dataframe(self, **kwargs):
            seen.update(kwargs)
            return pd.DataFrame({"timestamp": [pd.Timestamp("2026-11-06")], "close": [1.0]})

    engine._data_loader = Loader()
    await engine._fetch_ohlcv("069500", days=10)
    assert seen["cache_freshness_days"] == 0  # 이전: 기본 1일 → 15:35에 당일 종가 미반영


@pytest.mark.asyncio
async def test_etf_mode_uses_etf_universe_not_stock_screen(monkeypatch) -> None:
    from src.adapters.database.models.stock_universe import MarketType

    seen = {}

    class FakeScreener:
        def __init__(self, *a, **k):
            pass

        async def get_screening_candidates(self, market=None):
            seen["market"] = market
            raise RuntimeError("stop after candidate query")

    monkeypatch.setattr(engine_module, "StockScreener", FakeScreener)
    monkeypatch.setattr(engine_module.settings, "etf_universe_enabled", True)
    engine = _engine()
    engine.strategy_repo = SimpleNamespace(
        get_by_id=AsyncMock(
            return_value=SimpleNamespace(id=1, config_json="{}", symbol_list=[], account_no="1")
        )
    )
    engine._benchmark_change_today = AsyncMock(return_value=0.0)
    engine._evaluate_entry_regime = AsyncMock(return_value=True)
    engine._init_safety_guard = AsyncMock(
        return_value=SimpleNamespace(update_market_change=lambda x: None)
    )
    engine.symbol_state_repo = SimpleNamespace(get_in_position=AsyncMock(return_value=[]))

    await engine.execute(strategy_id=1, dry_run=True)

    assert seen["market"] == MarketType.ETF
