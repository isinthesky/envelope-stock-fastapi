from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pandas as pd
import pytest

from src.adapters.database.models.strategy_signal import SignalStatus, SignalType
from src.adapters.database.models.strategy_symbol_state import SymbolState
from src.application.domain.strategy.dto import GoldenCrossConfigDTO, GoldenCrossMAConfig
from src.application.domain.strategy.golden_cross_engine import GoldenCrossEngine
from src.application.domain.strategy.state_machine import Signal, StateTransition

# 합성데이터(180행)에 맞춘 소형 MA로 고정 — 엔진의 데이터 충분성 가드
# (len(df) < long_period+10)를 settings 기본값(라이브 200)과 무관하게 통과시킨다.
_TEST_CONFIG = GoldenCrossConfigDTO(ma_config=GoldenCrossMAConfig(short_period=5, long_period=60))


class _RecordingSymbolStateRepo:
    def __init__(self, state=None) -> None:
        self.state = state
        self.upsert_calls = 0
        self.update_indicators_calls = 0
        self.update_highest_price_calls = 0
        self.activate_trailing_stop_calls = 0
        self.update_state_calls = 0
        self.reset_to_waiting_calls = 0

    async def get_by_strategy_and_symbol(self, strategy_id: int, symbol: str):
        _ = strategy_id, symbol
        return self.state

    async def upsert(self, **kwargs):
        _ = kwargs
        self.upsert_calls += 1
        return self.state

    async def update_indicators(self, **kwargs):
        _ = kwargs
        self.update_indicators_calls += 1

    async def update_highest_price(self, **kwargs):
        _ = kwargs
        self.update_highest_price_calls += 1

    async def activate_trailing_stop(self, **kwargs):
        _ = kwargs
        self.activate_trailing_stop_calls += 1

    async def update_state(self, **kwargs):
        _ = kwargs
        self.update_state_calls += 1

    async def reset_to_waiting(self, *args):
        _ = args
        self.reset_to_waiting_calls += 1

    @property
    def write_count(self) -> int:
        return (
            self.upsert_calls
            + self.update_indicators_calls
            + self.update_highest_price_calls
            + self.activate_trailing_stop_calls
            + self.update_state_calls
            + self.reset_to_waiting_calls
        )


class _FailingSignalRepo:
    async def create_signal(self, **kwargs):
        _ = kwargs
        raise AssertionError("dry-run must not persist strategy signals")

    async def update_execution(self, *args, **kwargs):
        _ = args, kwargs
        raise AssertionError("dry-run must not update strategy signals")


class _FakeStateMachine:
    def __init__(self, transition: StateTransition) -> None:
        self.transition = transition

    def get_initial_state(self, current):
        _ = current
        return SymbolState.WAITING_FOR_GC

    def process(self, **kwargs):
        _ = kwargs
        return self.transition


def _sample_ohlcv(rows: int = 180) -> pd.DataFrame:
    prices = [100.0 + (idx % 3) for idx in range(rows)]
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=rows, freq="D"),
            "open": prices,
            "high": [price + 1 for price in prices],
            "low": [price - 1 for price in prices],
            "close": prices,
            "volume": [1000000] * rows,
        }
    )


def _add_indicators(df: pd.DataFrame, *args, **kwargs) -> pd.DataFrame:
    _ = args, kwargs
    result = df.copy()
    result["ma_short"] = Decimal("110")
    result["ma_long"] = Decimal("100")
    result["stoch_k"] = 35.0
    result["stoch_d"] = 25.0
    return result


@pytest.mark.asyncio
async def test_dry_run_does_not_create_or_update_symbol_state(monkeypatch: pytest.MonkeyPatch):
    engine = GoldenCrossEngine(session=SimpleNamespace(), kis_client=SimpleNamespace())
    state_repo = _RecordingSymbolStateRepo(state=None)
    engine.symbol_state_repo = state_repo
    engine.signal_repo = _FailingSignalRepo()
    engine._fetch_ohlcv = AsyncMock(return_value=_sample_ohlcv())
    monkeypatch.setattr(
        "src.application.domain.strategy.golden_cross_engine.TechnicalIndicators.prepare_golden_cross_indicators",
        _add_indicators,
    )

    result = await engine._process_symbol(
        strategy=SimpleNamespace(id=1),
        symbol="005930",
        config=_TEST_CONFIG,
        state_machine=_FakeStateMachine(
            StateTransition(
                new_state=SymbolState.WAITING_FOR_PULLBACK,
                signal=Signal.HOLD,
                reason="dry-run hold transition",
            )
        ),
        safety_guard=SimpleNamespace(),
        dry_run=True,
    )

    assert result is None
    assert state_repo.write_count == 0


@pytest.mark.asyncio
async def test_dry_run_signal_returns_skipped_dto_without_persisting(
    monkeypatch: pytest.MonkeyPatch,
):
    engine = GoldenCrossEngine(session=SimpleNamespace(), kis_client=SimpleNamespace())
    state_repo = _RecordingSymbolStateRepo(
        state=SimpleNamespace(
            state=SymbolState.READY_TO_BUY.value,
            gc_date=None,
            pullback_date=None,
            entry_price=None,
            entry_date=None,
            highest_price=None,
            trailing_stop_activated=False,
        )
    )
    engine.symbol_state_repo = state_repo
    engine.signal_repo = _FailingSignalRepo()
    engine._fetch_ohlcv = AsyncMock(return_value=_sample_ohlcv())
    monkeypatch.setattr(
        "src.application.domain.strategy.golden_cross_engine.TechnicalIndicators.prepare_golden_cross_indicators",
        _add_indicators,
    )

    result = await engine._process_symbol(
        strategy=SimpleNamespace(id=1),
        symbol="005930",
        config=_TEST_CONFIG,
        state_machine=_FakeStateMachine(
            StateTransition(
                new_state=SymbolState.IN_POSITION,
                signal=Signal.BUY,
                reason="dry-run buy",
                gc_date=datetime(2024, 1, 1),
                pullback_date=datetime(2024, 1, 2),
            )
        ),
        safety_guard=SimpleNamespace(),
        dry_run=True,
    )

    assert result is not None
    assert result.id == 0
    assert result.signal_type == SignalType.BUY.value
    assert result.signal_status == SignalStatus.SKIPPED.value
    assert result.prev_state == SymbolState.READY_TO_BUY.value
    assert result.new_state == SymbolState.IN_POSITION.value
    assert state_repo.write_count == 0


class _SignalRepoWithHistory:
    """직전 EXECUTED 시그널을 반환하되, create_signal이 호출되면 실패시킨다."""

    def __init__(self, existing) -> None:
        self.existing = existing

    async def get_by_symbol(self, strategy_id: int, symbol: str, limit: int = 50):
        _ = strategy_id, symbol, limit
        return [self.existing]

    async def create_signal(self, **kwargs):
        _ = kwargs
        raise AssertionError("중복 가드는 새 시그널 행을 만들면 안 됨")


@pytest.mark.asyncio
async def test_handle_signal_skips_when_same_transition_already_executed():
    """중복 주문 가드: 직전 실행에서 동일 전이가 이미 EXECUTED면 재주문/재기록하지 않는다."""
    existing = SimpleNamespace(
        id=42,
        strategy_id=1,
        symbol="005930",
        signal_type=SignalType.BUY.value,
        signal_status=SignalStatus.EXECUTED.value,
        prev_state=SymbolState.READY_TO_BUY.value,
        new_state=SymbolState.IN_POSITION.value,
    )
    engine = GoldenCrossEngine(session=SimpleNamespace(), kis_client=SimpleNamespace())
    engine.signal_repo = _SignalRepoWithHistory(existing)
    engine._execute_buy = AsyncMock(side_effect=AssertionError("중복인데 주문하면 안 됨"))

    result = await engine._handle_signal(
        strategy=SimpleNamespace(id=1, account_no="dummy"),
        symbol="005930",
        transition=StateTransition(
            new_state=SymbolState.IN_POSITION,
            signal=Signal.BUY,
            reason="stale 상태에서 동일 전이 재도출",
        ),
        current_snapshot=SimpleNamespace(
            close=Decimal("101"),
            ma_short=Decimal("110"),
            ma_long=Decimal("100"),
            stoch_k=35.0,
            stoch_d=25.0,
        ),
        state=SimpleNamespace(state=SymbolState.READY_TO_BUY.value),
        config=SimpleNamespace(),
        safety_guard=SimpleNamespace(),
        dry_run=False,
    )

    assert result is not None
    assert result.signal_status == SignalStatus.SKIPPED.value
    engine._execute_buy.assert_not_called()
