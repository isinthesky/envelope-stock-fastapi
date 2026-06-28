from datetime import datetime
from decimal import Decimal

import pytest

from src.application.common.exceptions import BacktestError
from src.application.domain.backtest.dto import (
    BacktestResultDTO,
    MultiSymbolBacktestRequestDTO,
    MultiSymbolBacktestResultDTO,
)
from src.application.domain.backtest.service import BacktestService
from src.application.domain.strategy.dto import StrategyConfigDTO


def _make_result(symbol: str, total_return: float, win_rate: float, mdd: float, total_trades: int, avg_holding_days: float) -> BacktestResultDTO:
    now = datetime(2024, 1, 1)
    return BacktestResultDTO(
        symbol=symbol,
        start_date=now,
        end_date=now,
        initial_capital=Decimal("10000000"),
        final_capital=Decimal("11000000"),
        execution_timing="next_open",
        total_return=total_return,
        annualized_return=12.0,
        cagr=12.0,
        mdd=mdd,
        volatility=10.0,
        sharpe_ratio=1.2,
        sortino_ratio=1.4,
        calmar_ratio=1.1,
        var_95=2.0,
        total_trades=total_trades,
        winning_trades=3,
        losing_trades=2,
        win_rate=win_rate,
        profit_factor=1.5,
        avg_win=4.0,
        avg_loss=-2.0,
        avg_win_loss_ratio=2.0,
        avg_holding_days=avg_holding_days,
        max_consecutive_wins=2,
        max_consecutive_losses=1,
        trades=[],
        daily_stats=[],
    )


def test_summarize_multi_symbol_results_builds_sell_page_summary() -> None:
    service = BacktestService(market_data_service=None, db_session=None)
    multi = MultiSymbolBacktestResultDTO(
        results={
            "005930": _make_result("005930", 15.0, 60.0, -8.0, 4, 18.0),
            "000660": _make_result("000660", -5.0, 40.0, -12.0, 3, 14.0),
            "035420": _make_result("035420", 8.0, 55.0, -6.0, 5, 22.0),
        },
        total_count=3,
        success_count=3,
        failed_count=0,
    )

    summary = service.summarize_multi_symbol_results(multi)

    assert summary.requested_count == 3
    assert summary.success_count == 3
    assert summary.failed_count == 0
    assert summary.profitable_symbols == 2
    assert summary.profitable_ratio == 66.67
    assert summary.total_trades == 12
    assert summary.best_symbols[0].symbol == "005930"
    assert summary.worst_symbols[0].symbol == "000660"


def test_build_universe_backtest_result_wraps_summary_and_results() -> None:
    service = BacktestService(market_data_service=None, db_session=None)
    now = datetime(2024, 1, 1)
    request = MultiSymbolBacktestRequestDTO(
        symbols=["005930"],
        start_date=now,
        end_date=datetime(2024, 12, 31),
        strategy_type="golden_cross",
        strategy_params={"short_period": 55},
        strategy_config=StrategyConfigDTO(),
    )
    multi = MultiSymbolBacktestResultDTO(
        results={"005930": _make_result("005930", 12.5, 57.1, -7.0, 7, 19.0)},
        total_count=1,
        success_count=1,
        failed_count=0,
    )

    result = service.build_universe_backtest_result(
        market="KOSPI",
        eligible_only=True,
        symbols=["005930"],
        request=request,
        multi_result=multi,
        config_summary={"label": "공격형 중단기 스윙 매도 v1"},
    )

    assert result.market == "KOSPI"
    assert result.eligible_only is True
    assert result.portfolio_summary is None
    assert result.summary.summary_type == "non_portfolio_diagnostic"
    assert result.diagnostic_summary.summary_type == "non_portfolio_diagnostic"
    assert result.summary.average_return == 12.5
    assert result.summary.average_win_rate == 57.1
    assert result.summary.best_symbols[0].symbol == "005930"
    assert "005930" in result.results


def test_build_universe_backtest_result_rejects_zero_max_positions() -> None:
    # Given
    service = BacktestService(market_data_service=None, db_session=None)
    now = datetime(2024, 1, 1)
    request = MultiSymbolBacktestRequestDTO(
        symbols=["005930"],
        start_date=now,
        end_date=datetime(2024, 12, 31),
        strategy_type="golden_cross",
        strategy_params={"short_period": 55},
        strategy_config=StrategyConfigDTO(),
    )
    multi = MultiSymbolBacktestResultDTO(
        results={"005930": _make_result("005930", 12.5, 57.1, -7.0, 7, 19.0)},
        total_count=1,
        success_count=1,
        failed_count=0,
    )

    # When / Then
    with pytest.raises(BacktestError, match="max_positions must be at least 1"):
        service.build_universe_backtest_result(
            market="KOSPI",
            eligible_only=True,
            symbols=["005930"],
            request=request,
            multi_result=multi,
            config_summary={"label": "공격형 중단기 스윙 매도 v1"},
            portfolio_enabled=True,
            max_positions=0,
        )
