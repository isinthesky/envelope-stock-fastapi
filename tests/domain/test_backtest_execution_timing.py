from datetime import datetime
from decimal import Decimal

import pandas as pd

from src.application.domain.backtest.dto import BacktestConfigDTO, ExecutionTiming
from src.application.domain.backtest.engine import BacktestEngine
from src.application.domain.strategy.dto import (
    BollingerBandConfig,
    EnvelopeConfig,
    PositionConfig,
    RiskManagementConfig,
    StrategyConfigDTO,
)


class BuyOnFirstBarSignalGenerator:
    @property
    def min_period(self) -> int:
        return 1

    def reset(self) -> None:
        pass

    def generate_signal(self, **kwargs) -> str:
        return "buy"


def _strategy_config() -> StrategyConfigDTO:
    return StrategyConfigDTO(
        bollinger_band=BollingerBandConfig(period=20, std_multiplier=2.0),
        envelope=EnvelopeConfig(period=20, percentage=2.0),
        position=PositionConfig(allocation_ratio=0.5, max_position_count=1),
        risk_management=RiskManagementConfig(
            use_stop_loss=False,
            use_take_profit=False,
            use_trailing_stop=False,
            use_atr_stop_loss=False,
            use_atr_trailing_stop=False,
        ),
    )


def _backtest_config(execution_timing: ExecutionTiming = "next_open") -> BacktestConfigDTO:
    return BacktestConfigDTO(
        initial_capital=Decimal("1000000"),
        use_commission=False,
        use_tax=False,
        use_slippage=False,
        execution_timing=execution_timing,
    )


def _daily_data() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": pd.date_range(start="2024-01-01", periods=3, freq="D"),
            "open": [90.0, 120.0, 130.0],
            "high": [110.0, 125.0, 135.0],
            "low": [80.0, 115.0, 125.0],
            "close": [100.0, 121.0, 131.0],
            "volume": [1000000, 1000000, 1000000],
        }
    )


async def test_same_close_execution_fills_buy_signal_at_signal_day_close_when_explicit() -> None:
    # Given
    data = _daily_data()
    engine = BacktestEngine(
        symbol="005930",
        strategy_config=_strategy_config(),
        backtest_config=_backtest_config(execution_timing="same_close"),
    )
    engine.signal_generator = BuyOnFirstBarSignalGenerator()

    # When
    result = await engine.run(
        data=data,
        start_date=datetime(2024, 1, 1),
        end_date=datetime(2024, 1, 3),
    )

    # Then
    assert result.execution_timing == "same_close"
    assert result.trades[0].entry_date == datetime(2024, 1, 1)
    assert result.trades[0].entry_price == Decimal("100.0")


async def test_default_daily_execution_fills_buy_signal_at_next_open() -> None:
    # Given
    data = _daily_data()
    engine = BacktestEngine(
        symbol="005930",
        strategy_config=_strategy_config(),
        backtest_config=_backtest_config(),
    )
    engine.signal_generator = BuyOnFirstBarSignalGenerator()

    # When
    result = await engine.run(
        data=data,
        start_date=datetime(2024, 1, 1),
        end_date=datetime(2024, 1, 3),
    )

    # Then
    assert result.execution_timing == "next_open"
    assert result.trades[0].entry_date == datetime(2024, 1, 2)
    assert result.trades[0].entry_price == Decimal("120.0")


async def test_next_close_execution_fills_buy_signal_at_next_day_close() -> None:
    # Given
    data = _daily_data()
    engine = BacktestEngine(
        symbol="005930",
        strategy_config=_strategy_config(),
        backtest_config=_backtest_config(execution_timing="next_close"),
    )
    engine.signal_generator = BuyOnFirstBarSignalGenerator()

    # When
    result = await engine.run(
        data=data,
        start_date=datetime(2024, 1, 1),
        end_date=datetime(2024, 1, 3),
    )

    # Then
    assert result.execution_timing == "next_close"
    assert result.trades[0].entry_date == datetime(2024, 1, 2)
    assert result.trades[0].entry_price == Decimal("121.0")
