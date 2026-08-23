from datetime import datetime
from decimal import Decimal

from src.adapters.database.models.strategy_symbol_state import SymbolState
from src.application.domain.backtest.position_manager import PositionManager
from src.application.domain.strategy.dto import GoldenCrossConfigDTO
from src.application.domain.strategy.risk_contract import (
    DEFAULT_PEAK_DRAWDOWN_STOP_RATIO,
    effective_peak_price,
    is_peak_drawdown_stop_triggered,
    peak_drawdown_ratio,
)
from src.application.domain.strategy.state_machine import (
    GoldenCrossStateMachine,
    IndicatorSnapshot,
    Signal,
)
from src.application.domain.strategy.strategy_contract import GoldenCrossRiskExitReason


def _snapshot(close: Decimal) -> IndicatorSnapshot:
    return IndicatorSnapshot(
        timestamp=datetime(2026, 8, 24),
        close=close,
        ma_short=Decimal("110"),
        ma_long=Decimal("100"),
        stoch_k=40.0,
        stoch_d=30.0,
    )


def test_peak_drawdown_contract_triggers_at_inclusive_fifteen_percent() -> None:
    assert DEFAULT_PEAK_DRAWDOWN_STOP_RATIO == 0.15
    assert (
        peak_drawdown_ratio(
            current_price=Decimal("102"),
            entry_price=Decimal("100"),
            highest_price=Decimal("120"),
        )
        == 0.15
    )
    assert is_peak_drawdown_stop_triggered(
        current_price=Decimal("102"),
        entry_price=Decimal("100"),
        highest_price=Decimal("120"),
    )


def test_effective_peak_price_never_decreases() -> None:
    assert effective_peak_price(current_price=140, entry_price=100, highest_price=120) == 140
    assert effective_peak_price(current_price=118, entry_price=100, highest_price=140) == 140


def test_live_state_machine_stops_profitable_position_after_peak_drawdown() -> None:
    machine = GoldenCrossStateMachine(GoldenCrossConfigDTO())

    transition = machine.process(
        current=_snapshot(Decimal("102")),
        prev=_snapshot(Decimal("103")),
        current_state=SymbolState.IN_POSITION,
        entry_price=Decimal("100"),
        entry_date=datetime(2026, 8, 1),
        highest_price=Decimal("120"),
    )

    assert transition.signal == Signal.SELL
    assert transition.reason == GoldenCrossRiskExitReason.STOP_LOSS.value


def test_atr_stop_is_opt_in_and_uses_live_state_machine() -> None:
    config = GoldenCrossConfigDTO(
        risk_config={
            "use_stop_loss": True,
            "use_take_profit": False,
            "use_trailing_stop": False,
            "use_atr_stop_loss": True,
            "atr_stop_loss_multiplier": 2.0,
        }
    )
    machine = GoldenCrossStateMachine(config)
    current = _snapshot(Decimal("95"))
    current.atr = Decimal("2")

    transition = machine.process(
        current=current,
        prev=_snapshot(Decimal("100")),
        current_state=SymbolState.IN_POSITION,
        entry_price=Decimal("100"),
        highest_price=Decimal("100"),
    )

    assert transition.signal == Signal.SELL
    assert transition.reason == GoldenCrossRiskExitReason.STOP_LOSS.value


def test_backtest_stop_loss_uses_position_highest_price() -> None:
    manager = PositionManager()
    manager.open_position("005930", 1, Decimal("100"), datetime(2026, 8, 1), 1)
    position = manager.get_position("005930")
    assert position is not None
    position.highest_price = Decimal("120")

    assert manager.check_stop_loss(position, Decimal("102"), -0.15)
    assert not manager.check_stop_loss(position, Decimal("103"), -0.15)


def test_stored_stop_loss_ratio_cannot_override_fixed_fifteen_percent_contract() -> None:
    config = GoldenCrossConfigDTO(risk_config={"stop_loss_ratio": -0.05})
    assert config.risk_config.stop_loss_ratio == -0.15
    config.risk_config.stop_loss_ratio = -0.03
    assert config.risk_config.stop_loss_ratio == -0.15
    machine = GoldenCrossStateMachine(config)

    transition = machine.process(
        current=_snapshot(Decimal("110")),
        prev=_snapshot(Decimal("111")),
        current_state=SymbolState.IN_POSITION,
        entry_price=Decimal("100"),
        highest_price=Decimal("120"),
    )

    assert transition.signal == Signal.HOLD


def test_backtest_atr_entry_stop_uses_current_atr_like_live_state_machine() -> None:
    manager = PositionManager()
    manager.open_position("005930", 1, Decimal("100"), datetime(2026, 8, 1), 1, entry_atr=2.0)
    position = manager.get_position("005930")
    assert position is not None
    manager.update_position_atr("005930", 5.0)

    assert not manager.check_atr_stop_loss(position, Decimal("92"), 2.0)
    assert manager.check_atr_stop_loss(position, Decimal("90"), 2.0)


def test_zero_current_atr_does_not_fall_back_to_entry_atr() -> None:
    manager = PositionManager()
    manager.open_position("005930", 1, Decimal("100"), datetime(2026, 8, 1), 1, entry_atr=5.0)
    position = manager.get_position("005930")
    assert position is not None
    manager.update_position_atr("005930", 0.0)

    assert manager.check_atr_stop_loss(position, Decimal("95"), 2.0)
