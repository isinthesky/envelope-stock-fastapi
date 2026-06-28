from datetime import datetime
from decimal import Decimal

from src.application.domain.backtest.dto import BacktestResultDTO, MultiSymbolBacktestResultDTO, TradeDTO
from src.application.domain.backtest.service import BacktestService


def _completed_trade(
    symbol: str,
    exit_price: Decimal,
    profit_rate: float,
) -> TradeDTO:
    return TradeDTO(
        trade_id=1,
        symbol=symbol,
        trade_type="buy",
        entry_date=datetime(2024, 1, 2),
        entry_price=Decimal("100"),
        exit_date=datetime(2024, 1, 5),
        exit_price=exit_price,
        quantity=1,
        commission=Decimal("0"),
        tax=Decimal("0"),
        profit=exit_price - Decimal("100"),
        profit_rate=profit_rate,
        holding_days=3,
        exit_reason="signal",
    )


def _result(symbol: str, total_return: float, benchmark_return: float) -> BacktestResultDTO:
    start = datetime(2024, 1, 1)
    return BacktestResultDTO(
        symbol=symbol,
        start_date=start,
        end_date=datetime(2024, 1, 5),
        initial_capital=Decimal("1000000"),
        final_capital=Decimal("1000000"),
        execution_timing="next_open",
        total_return=total_return,
        annualized_return=total_return,
        cagr=total_return,
        mdd=0.0,
        volatility=0.0,
        sharpe_ratio=0.0,
        sortino_ratio=0.0,
        calmar_ratio=0.0,
        var_95=0.0,
        total_trades=1,
        winning_trades=1,
        losing_trades=0,
        win_rate=100.0,
        profit_factor=0.0,
        avg_win=total_return,
        avg_loss=0.0,
        avg_win_loss_ratio=0.0,
        avg_holding_days=3.0,
        max_consecutive_wins=1,
        max_consecutive_losses=0,
        benchmark_return=benchmark_return,
        trades=[_completed_trade(symbol, Decimal("100") * (Decimal("1") + Decimal(str(total_return)) / Decimal("100")), total_return)],
        daily_stats=[],
    )


def test_portfolio_simulation_ranks_simultaneous_candidates_against_shared_cash() -> None:
    # Given
    service = BacktestService(market_data_service=None, db_session=None)
    multi_result = MultiSymbolBacktestResultDTO(
        results={
            "005930": _result("005930", 20.0, 8.0),
            "000660": _result("000660", 30.0, 12.0),
        },
        total_count=2,
        success_count=2,
        failed_count=0,
    )

    # When
    portfolio = service.simulate_universe_portfolio(
        multi_result,
        initial_capital=Decimal("1000000"),
        max_positions=1,
    )

    # Then
    assert portfolio.max_positions == 1
    assert portfolio.entered_positions == 1
    assert portfolio.rejected_candidates == 1
    assert portfolio.trades[0].symbol == "000660"
    assert portfolio.total_return == 30.0
    assert portfolio.benchmark_return == 10.0
    assert portfolio.excess_return == 20.0
    assert portfolio.mdd == 0.0
