from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pandas as pd
import pytest

from src.adapters.database.models.strategy_signal import SignalStatus, SignalType
from src.adapters.database.models.strategy_symbol_state import SymbolState
from src.application.domain.strategy.dto import GoldenCrossConfigDTO
from src.application.domain.strategy.golden_cross_engine import GoldenCrossEngine
from src.application.domain.strategy.state_machine import Signal, StateTransition


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
        config=GoldenCrossConfigDTO(),
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
        config=GoldenCrossConfigDTO(),
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
