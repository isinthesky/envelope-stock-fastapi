from datetime import datetime
from decimal import Decimal

import pytest

from src.adapters.database.models.strategy_symbol_state import SymbolState
from src.application.domain.backtest.dto import BacktestConfigDTO, TradeDTO
from src.application.domain.backtest.engine import BacktestEngine
from src.application.domain.strategy.dto import GoldenCrossConfigDTO, StrategyConfigDTO
from src.application.domain.strategy.state_machine import (
    GoldenCrossStateMachine,
    IndicatorSnapshot,
    Signal,
)
from src.application.domain.strategy.strategy_contract import GoldenCrossRiskExitReason

ENTRY_DATE = datetime(2024, 1, 1)
SYMBOL = "005930"


def _snapshot(
    timestamp: datetime,
    close: Decimal,
    ma_short: Decimal = Decimal("110"),
    ma_long: Decimal = Decimal("100"),
) -> IndicatorSnapshot:
    return IndicatorSnapshot(
        timestamp=timestamp,
        close=close,
        ma_short=ma_short,
        ma_long=ma_long,
        stoch_k=40.0,
        stoch_d=30.0,
    )


def _make_backtest_engine(
    strategy_config: StrategyConfigDTO,
    *,
    entry_price: Decimal = Decimal("100"),
    highest_price: Decimal | None = None,
    trailing_stop_activated: bool = False,
    strategy_params: dict | None = None,
) -> BacktestEngine:
    engine = BacktestEngine(
        symbol=SYMBOL,
        strategy_config=strategy_config,
        backtest_config=BacktestConfigDTO(
            use_commission=False,
            use_tax=False,
            use_slippage=False,
        ),
        strategy_params=strategy_params,
    )
    engine.position_manager.open_position(SYMBOL, 1, entry_price, ENTRY_DATE, 1)
    position = engine.position_manager.get_position(SYMBOL)
    assert position is not None
    position.highest_price = highest_price or entry_price
    position.trailing_stop_activated = trailing_stop_activated
    engine.trades.append(
        TradeDTO(
            trade_id=1,
            symbol=SYMBOL,
            trade_type="buy",
            entry_date=ENTRY_DATE,
            entry_price=entry_price,
            quantity=1,
        )
    )
    return engine


def _exit_reason(engine: BacktestEngine) -> str | None:
    return engine.trades[0].exit_reason


@pytest.mark.asyncio
async def test_trailing_drawdown_without_activation_does_not_exit():
    # Given: price has drawn down enough from the high, but current PnL never reached activation.
    entry_price = Decimal("100")
    highest_price = Decimal("115")
    current_price = Decimal("106")
    check_date = datetime(2024, 1, 2)
    live_config = GoldenCrossConfigDTO()
    live_config.risk_config.trailing_stop_activation = 0.15
    live_config.risk_config.trailing_stop_distance = 0.07
    live_transition = GoldenCrossStateMachine(live_config).process(
        current=_snapshot(check_date, current_price),
        prev=_snapshot(ENTRY_DATE, highest_price),
        current_state=SymbolState.IN_POSITION,
        entry_price=entry_price,
        entry_date=ENTRY_DATE,
        highest_price=highest_price,
        trailing_stop_activated=False,
    )
    strategy_config = StrategyConfigDTO()
    strategy_config.risk_management.use_trailing_stop = True
    strategy_config.risk_management.trailing_stop_ratio = 0.07
    engine = _make_backtest_engine(
        strategy_config,
        entry_price=entry_price,
        highest_price=highest_price,
        strategy_params={
            "trailing_stop_activation": 0.15,
            "trailing_stop_distance": 0.07,
            "partial_take_profit_1": 0.99,
            "partial_take_profit_2": 0.99,
        },
    )

    # When: backtest risk management evaluates the same position.
    await engine._check_risk_management(check_date, current_price)

    # Then: both live and backtest keep holding because trailing stop was not activated.
    assert live_transition.signal == Signal.HOLD
    assert engine.position_manager.has_position(SYMBOL)
    assert _exit_reason(engine) is None


@pytest.mark.asyncio
async def test_backtest_trailing_stop_exit_reason_matches_live_after_activation():
    # Given: both paths have already activated trailing stop and price drew down from the high.
    entry_price = Decimal("100")
    highest_price = Decimal("115")
    current_price = Decimal("106")
    check_date = datetime(2024, 1, 2)
    live_config = GoldenCrossConfigDTO()
    live_config.risk_config.use_take_profit = False
    live_config.risk_config.trailing_stop_activation = 0.15
    live_config.risk_config.trailing_stop_distance = 0.07
    live_transition = GoldenCrossStateMachine(live_config).process(
        current=_snapshot(check_date, current_price),
        prev=_snapshot(ENTRY_DATE, highest_price),
        current_state=SymbolState.IN_POSITION,
        entry_price=entry_price,
        entry_date=ENTRY_DATE,
        highest_price=highest_price,
        trailing_stop_activated=True,
    )
    strategy_config = StrategyConfigDTO()
    strategy_config.risk_management.use_trailing_stop = True
    strategy_config.risk_management.trailing_stop_ratio = 0.07
    engine = _make_backtest_engine(
        strategy_config,
        entry_price=entry_price,
        highest_price=highest_price,
        trailing_stop_activated=True,
        strategy_params={
            "partial_take_profit_1": 0.99,
            "partial_take_profit_2": 0.99,
        },
    )

    # When: backtest risk management evaluates the same activated trailing stop.
    await engine._check_risk_management(check_date, current_price)

    # Then: exit reasons use the same contract string.
    assert live_transition.reason == GoldenCrossRiskExitReason.TRAILING_STOP.value
    assert _exit_reason(engine) == GoldenCrossRiskExitReason.TRAILING_STOP.value


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reason", "current_price", "risk_mutation"),
    [
        (
            GoldenCrossRiskExitReason.STOP_LOSS.value,
            Decimal("85"),
            lambda config: setattr(config.risk_management, "use_stop_loss", True)
            or setattr(config.risk_management, "stop_loss_ratio", -0.15),
        ),
        (
            GoldenCrossRiskExitReason.TAKE_PROFIT.value,
            Decimal("121"),
            lambda config: setattr(config.risk_management, "use_take_profit", True)
            or setattr(config.risk_management, "take_profit_ratio", 0.20),
        ),
    ],
)
async def test_backtest_exit_reason_matches_live_for_stop_loss_and_take_profit(
    reason: str,
    current_price: Decimal,
    risk_mutation,
):
    # Given: live and backtest configs share the same stop/take-profit threshold.
    live_config = GoldenCrossConfigDTO()
    live_config.risk_config.stop_loss_ratio = -0.15
    live_config.risk_config.take_profit_ratio = 0.20
    live_transition = GoldenCrossStateMachine(live_config).process(
        current=_snapshot(datetime(2024, 1, 2), current_price),
        prev=_snapshot(ENTRY_DATE, Decimal("100")),
        current_state=SymbolState.IN_POSITION,
        entry_price=Decimal("100"),
        entry_date=ENTRY_DATE,
        highest_price=Decimal("100"),
    )
    strategy_config = StrategyConfigDTO()
    risk_mutation(strategy_config)
    engine = _make_backtest_engine(
        strategy_config,
        strategy_params={
            "partial_take_profit_1": 0.99,
            "partial_take_profit_2": 0.99,
        },
    )

    # When: backtest risk management evaluates the same threshold breach.
    await engine._check_risk_management(datetime(2024, 1, 2), current_price)

    # Then: exit reasons use the same contract string.
    assert live_transition.reason == reason
    assert _exit_reason(engine) == reason


@pytest.mark.asyncio
async def test_backtest_max_hold_exit_reason_matches_live_state_machine():
    # Given: both paths have exceeded the configured maximum holding period.
    live_config = GoldenCrossConfigDTO()
    live_config.risk_config.use_stop_loss = False
    live_config.risk_config.use_take_profit = False
    live_config.risk_config.use_trailing_stop = False
    live_config.risk_config.max_hold_days = 10
    check_date = datetime(2024, 1, 11)
    live_transition = GoldenCrossStateMachine(live_config).process(
        current=_snapshot(check_date, Decimal("101")),
        prev=_snapshot(ENTRY_DATE, Decimal("100")),
        current_state=SymbolState.IN_POSITION,
        entry_price=Decimal("100"),
        entry_date=ENTRY_DATE,
        highest_price=Decimal("101"),
    )
    strategy_config = StrategyConfigDTO()
    engine = _make_backtest_engine(
        strategy_config,
        strategy_params={
            "max_hold_days": 10,
            "partial_take_profit_1": 0.99,
            "partial_take_profit_2": 0.99,
        },
    )

    # When: backtest risk management evaluates the same max-hold boundary.
    await engine._check_risk_management(check_date, Decimal("101"))

    # Then: max-hold uses the live-compatible exit reason.
    assert live_transition.reason == GoldenCrossRiskExitReason.MAX_HOLD.value
    assert _exit_reason(engine) == GoldenCrossRiskExitReason.MAX_HOLD.value
