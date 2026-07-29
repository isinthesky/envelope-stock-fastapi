from datetime import datetime
from decimal import Decimal

from src.adapters.database.models.strategy_symbol_state import SymbolState
from src.application.domain.backtest.signal_generators import GoldenCrossSignalGenerator
from src.application.domain.strategy.dto import GoldenCrossConfigDTO, StochasticConfig
from src.application.domain.strategy.signal_evaluator import (
    GoldenCrossScanContext,
    GoldenCrossSignalEvaluator,
)
from src.application.domain.strategy.state_machine import (
    GoldenCrossStateMachine,
    IndicatorSnapshot,
    Signal,
)
from src.application.domain.strategy.strategy_contract import (
    GoldenCrossScanState,
    GoldenCrossStrategyContract,
    GoldenCrossTradeSignal,
    GoldenCrossTransitionReason,
)


def test_golden_cross_pullback_recovery_uses_one_buy_contract() -> None:
    # Given: the same golden-cross pullback recovery setup across scanner,
    # backtest, and live state-machine seams.
    scanner_context = GoldenCrossScanContext(
        is_gc_active=True,
        stoch_k=31.0,
        stoch_d=25.0,
        stoch_threshold=30.0,
        ma_gap_ratio=5.0,
        prev_stoch_k=25.0,
        recent_oversold=True,
        recovery_threshold=20.0,
        strong_recovery_threshold=30.0,
    )
    backtest_generator = GoldenCrossSignalGenerator(
        short_period=2,
        long_period=4,
        stoch_k_period=3,
        stoch_d_period=1,
    )
    live_machine = GoldenCrossStateMachine(
        GoldenCrossConfigDTO(
            stochastic_config=StochasticConfig(
                oversold_threshold=30.0,
                recovery_threshold=20.0,
                strong_recovery_threshold=30.0,
            )
        )
    )
    high_history = [100.0, 100.0, 100.0, 100.0]
    low_history = [0.0, 0.0, 0.0, 0.0]
    for pullback_closes in ([10.0, 20.0, 25.0, 25.0], [20.0, 25.0, 25.0, 25.0]):
        assert (
            backtest_generator.generate_signal(
                price_history=pullback_closes,
                current_price=Decimal(str(pullback_closes[-1])),
                high_history=high_history,
                low_history=low_history,
                close_history=pullback_closes,
            )
            == GoldenCrossTradeSignal.HOLD.value
        )
    prev_snapshot = IndicatorSnapshot(
        timestamp=datetime(2024, 1, 2),
        close=Decimal("25"),
        ma_short=Decimal("105"),
        ma_long=Decimal("100"),
        stoch_k=25.0,
        stoch_d=25.0,
    )
    current_snapshot = IndicatorSnapshot(
        timestamp=datetime(2024, 1, 3),
        close=Decimal("31"),
        ma_short=Decimal("105"),
        ma_long=Decimal("100"),
        stoch_k=31.0,
        stoch_d=25.0,
    )

    # When: each seam classifies the recovery bar.
    scanner_state = GoldenCrossSignalEvaluator.classify_scan_state(scanner_context)
    backtest_signal = backtest_generator.generate_signal(
        price_history=[25.0, 25.0, 25.0, 31.0],
        current_price=Decimal("31"),
        high_history=high_history,
        low_history=low_history,
        close_history=[25.0, 25.0, 25.0, 31.0],
    )
    live_transition = live_machine.process(
        current=current_snapshot,
        prev=prev_snapshot,
        current_state=SymbolState.READY_TO_BUY,
        pullback_date=prev_snapshot.timestamp,
    )

    # Then: scanner naming, backtest signal naming, and live transition naming agree.
    assert scanner_state == GoldenCrossScanState.OPTIMAL_BUY.value
    assert backtest_signal == GoldenCrossTradeSignal.BUY.value
    assert live_transition.new_state == SymbolState.IN_POSITION
    assert live_transition.signal == Signal.BUY
    assert live_transition.reason == GoldenCrossTransitionReason.STOCH_STRONG_RECOVERY.value


def test_non_golden_cross_fixture_never_reaches_buy_or_ready_state() -> None:
    # Given: short MA is not above long MA, even though stochastic recovered.
    scanner_context = GoldenCrossScanContext(
        is_gc_active=False,
        stoch_k=31.0,
        stoch_d=25.0,
        stoch_threshold=30.0,
        ma_gap_ratio=-1.0,
        prev_stoch_k=25.0,
        recent_oversold=True,
        recovery_threshold=20.0,
        strong_recovery_threshold=30.0,
    )
    backtest_generator = GoldenCrossSignalGenerator(
        short_period=2,
        long_period=4,
        stoch_k_period=3,
        stoch_d_period=1,
    )
    live_machine = GoldenCrossStateMachine()
    high_history = [100.0, 100.0, 100.0, 100.0]
    low_history = [0.0, 0.0, 0.0, 0.0]
    for pullback_closes in ([35.0, 35.0, 25.0, 25.0], [35.0, 35.0, 25.0, 25.0]):
        assert (
            backtest_generator.generate_signal(
                price_history=pullback_closes,
                current_price=Decimal(str(pullback_closes[-1])),
                high_history=high_history,
                low_history=low_history,
                close_history=pullback_closes,
            )
            != GoldenCrossTradeSignal.BUY.value
        )
    prev_snapshot = IndicatorSnapshot(
        timestamp=datetime(2024, 1, 2),
        close=Decimal("25"),
        ma_short=Decimal("95"),
        ma_long=Decimal("100"),
        stoch_k=25.0,
        stoch_d=25.0,
    )
    current_snapshot = IndicatorSnapshot(
        timestamp=datetime(2024, 1, 3),
        close=Decimal("31"),
        ma_short=Decimal("95"),
        ma_long=Decimal("100"),
        stoch_k=31.0,
        stoch_d=25.0,
    )

    # When: each seam classifies the non-GC recovery bar.
    scanner_state = GoldenCrossSignalEvaluator.classify_scan_state(scanner_context)
    backtest_signal = backtest_generator.generate_signal(
        price_history=[35.0, 35.0, 25.0, 31.0],
        current_price=Decimal("31"),
        high_history=high_history,
        low_history=low_history,
        close_history=[35.0, 35.0, 25.0, 31.0],
    )
    live_transition = live_machine.process(
        current=current_snapshot,
        prev=prev_snapshot,
        current_state=SymbolState.WAITING_FOR_PULLBACK,
    )

    # Then: MA short <= MA long never yields a buy or ready state.
    assert scanner_state == GoldenCrossScanState.NOT_GC.value
    assert scanner_state not in GoldenCrossStrategyContract.buy_candidate_state_values()
    assert backtest_signal != GoldenCrossTradeSignal.BUY.value
    assert live_transition.new_state == SymbolState.WAITING_FOR_GC
    assert live_transition.signal == Signal.HOLD
    assert live_transition.reason == GoldenCrossTransitionReason.GC_INVALIDATED.value


def test_live_entry_rejects_falling_or_non_momentum_recovery() -> None:
    """A READY_TO_BUY state cannot bypass the scanner's recovery predicate."""
    machine = GoldenCrossStateMachine(
        GoldenCrossConfigDTO(
            stochastic_config=StochasticConfig(
                oversold_threshold=30.0,
                recovery_threshold=20.0,
                strong_recovery_threshold=30.0,
                require_momentum_turn=True,
            )
        )
    )
    previous = IndicatorSnapshot(
        timestamp=datetime(2024, 1, 2),
        close=Decimal("35"),
        ma_short=Decimal("105"),
        ma_long=Decimal("100"),
        stoch_k=40.0,
        stoch_d=25.0,
    )
    current = IndicatorSnapshot(
        timestamp=datetime(2024, 1, 3),
        close=Decimal("34"),
        ma_short=Decimal("105"),
        ma_long=Decimal("100"),
        stoch_k=35.0,
        stoch_d=40.0,
    )

    transition = machine.process(
        current=current,
        prev=previous,
        current_state=SymbolState.READY_TO_BUY,
        pullback_date=datetime(2024, 1, 1),
    )

    assert transition.new_state == SymbolState.READY_TO_BUY
    assert transition.signal == Signal.HOLD


def test_bootstrapped_ready_state_allows_recovery_without_pullback_date() -> None:
    machine = GoldenCrossStateMachine(
        GoldenCrossConfigDTO(
            stochastic_config=StochasticConfig(
                oversold_threshold=30.0,
                recovery_threshold=20.0,
                strong_recovery_threshold=30.0,
            )
        )
    )
    oversold = IndicatorSnapshot(
        timestamp=datetime(2024, 1, 2),
        close=Decimal("25"),
        ma_short=Decimal("105"),
        ma_long=Decimal("100"),
        stoch_k=25.0,
        stoch_d=25.0,
    )
    recovered = IndicatorSnapshot(
        timestamp=datetime(2024, 1, 3),
        close=Decimal("31"),
        ma_short=Decimal("105"),
        ma_long=Decimal("100"),
        stoch_k=31.0,
        stoch_d=25.0,
    )

    initial_state = machine.get_initial_state(oversold)
    transition = machine.process(
        current=recovered,
        prev=oversold,
        current_state=initial_state,
        pullback_date=None,
    )

    assert initial_state == SymbolState.READY_TO_BUY
    assert transition.new_state == SymbolState.IN_POSITION
    assert transition.signal == Signal.BUY


def test_ready_state_holds_when_long_ma_is_non_positive() -> None:
    machine = GoldenCrossStateMachine()
    previous = IndicatorSnapshot(
        timestamp=datetime(2024, 1, 2),
        close=Decimal("25"),
        ma_short=Decimal("1"),
        ma_long=Decimal("0"),
        stoch_k=25.0,
        stoch_d=25.0,
    )
    current = IndicatorSnapshot(
        timestamp=datetime(2024, 1, 3),
        close=Decimal("31"),
        ma_short=Decimal("1"),
        ma_long=Decimal("0"),
        stoch_k=31.0,
        stoch_d=25.0,
    )

    transition = machine.process(
        current=current,
        prev=previous,
        current_state=SymbolState.READY_TO_BUY,
        pullback_date=previous.timestamp,
    )

    assert transition.new_state == SymbolState.READY_TO_BUY
    assert transition.signal == Signal.HOLD
