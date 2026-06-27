from decimal import Decimal
from types import SimpleNamespace

import pandas as pd

from src.application.domain.backtest.dto import BacktestConfigDTO
from src.application.domain.backtest.engine import BacktestEngine
from src.application.domain.backtest.signal_generators import GoldenCrossSignalGenerator
from src.application.domain.strategy.dto import (
    BollingerBandConfig,
    EnvelopeConfig,
    PositionConfig,
    RiskManagementConfig,
    StrategyConfigDTO,
)


def test_golden_cross_stochastic_uses_ohlc_when_available() -> None:
    generator = GoldenCrossSignalGenerator(stoch_k_period=14, stoch_d_period=3)
    closes = [float(i) for i in range(1, 18)]
    highs = [100.0] * len(closes)
    lows = [0.0] * len(closes)

    ohlc_k, ohlc_d = generator._calculate_stochastic(
        closes,
        high_history=highs,
        low_history=lows,
    )
    close_only_k, close_only_d = generator._calculate_stochastic(closes)

    assert ohlc_k == 17.0
    assert ohlc_d == 16.0
    assert close_only_k == 100.0
    assert close_only_d == 100.0


def test_golden_cross_backtest_engine_passes_ohlc_history_to_signal_generator() -> None:
    strategy_config = StrategyConfigDTO(
        bollinger_band=BollingerBandConfig(period=20, std_multiplier=2.0),
        envelope=EnvelopeConfig(period=20, percentage=2.0),
        position=PositionConfig(allocation_ratio=0.1, max_position_count=1),
        risk_management=RiskManagementConfig(),
    )
    backtest_config = BacktestConfigDTO(initial_capital=Decimal("10000000"))
    engine = BacktestEngine(
        symbol="005930",
        strategy_config=strategy_config,
        backtest_config=backtest_config,
        strategy_type="golden_cross",
    )
    engine.price_history = [1.0, 2.0, 3.0]
    engine.high_history = [10.0, 11.0, 12.0]
    engine.low_history = [0.5, 1.5, 2.5]
    engine.close_history = [1.0, 2.0, 3.0]

    calls = []

    def generate_signal(**kwargs):
        calls.append(kwargs)
        return "hold"

    engine.signal_generator = SimpleNamespace(generate_signal=generate_signal)

    assert engine._generate_signal(Decimal("3.0")) == "hold"
    assert calls[0]["high_history"] is engine.high_history
    assert calls[0]["low_history"] is engine.low_history
    assert calls[0]["close_history"] is engine.close_history


async def test_golden_cross_backtest_run_uses_ohlc_stochastic_for_trades() -> None:
    strategy_config = StrategyConfigDTO(
        bollinger_band=BollingerBandConfig(period=20, std_multiplier=2.0),
        envelope=EnvelopeConfig(period=20, percentage=2.0),
        position=PositionConfig(allocation_ratio=0.1, max_position_count=1),
        risk_management=RiskManagementConfig(),
    )
    backtest_config = BacktestConfigDTO(initial_capital=Decimal("10000000"))
    engine = BacktestEngine(
        symbol="005930",
        strategy_config=strategy_config,
        backtest_config=backtest_config,
        strategy_type="golden_cross",
        strategy_params={
            "short_period": 2,
            "long_period": 3,
            "stoch_k_period": 3,
            "stoch_d_period": 1,
            "stoch_oversold": 30.0,
            "buy_recovery_threshold": 35.0,
            "min_pullback_bars": 1,
            "min_reentry_cooldown_bars": 0,
        },
    )
    closes = [10.0, 20.0, 25.0, 25.0, 35.0, 40.0]
    data = pd.DataFrame(
        {
            "timestamp": pd.date_range(start="2024-01-01", periods=len(closes), freq="D"),
            "open": closes,
            "high": [100.0] * len(closes),
            "low": [0.0] * len(closes),
            "close": closes,
            "volume": [1000000] * len(closes),
        }
    )

    result = await engine.run(
        data=data,
        start_date=data["timestamp"].iloc[0].to_pydatetime(),
        end_date=data["timestamp"].iloc[-1].to_pydatetime(),
    )

    assert any(trade.trade_type == "buy" for trade in result.trades)
