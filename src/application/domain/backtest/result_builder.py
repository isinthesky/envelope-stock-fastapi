# -*- coding: utf-8 -*-
"""
Backtest Result Builder - 백테스트 성과 지표 집계 (단일 출처)

`BacktestEngine._generate_result`에서 추출한 순수 함수. 엔진과
`GoldenCrossParityReplay`(라이브 패리티 백테스트)가 **동일한 성과 계산 로직**을
공유하도록 하여, 검증 하네스가 산출하는 숫자와 기존 백테스트 엔진의 숫자가
정의상 일치하도록 보장한다.

행위 보존: 이 함수는 기존 엔진 로직을 그대로 옮긴 것이며 결과가 달라지지 않는다.
"""

from datetime import datetime
from decimal import Decimal

import pandas as pd

from src.application.common.performance_metrics import PerformanceMetrics
from src.application.domain.backtest.dto import (
    BacktestResultDTO,
    DailyStatsDTO,
    ExecutionTiming,
    TradeDTO,
)


def build_backtest_result(
    *,
    symbol: str,
    start_date: datetime,
    end_date: datetime,
    initial_capital: Decimal,
    execution_timing: ExecutionTiming,
    equity_curve: list[Decimal],
    daily_stats: list[DailyStatsDTO],
    trades: list[TradeDTO],
    completed_trades: list[dict],
) -> BacktestResultDTO:
    """일별 자산곡선/거래 이력으로부터 성과 지표를 집계한다.

    Args:
        completed_trades: 청산 완료된 거래의 요약 dict 리스트
            (각 원소는 ``{"profit_rate": float, "holding_days": int}``)
    """
    final_capital = equity_curve[-1] if equity_curve else initial_capital
    total_return = PerformanceMetrics.calculate_total_return(initial_capital, final_capital)
    annualized_return = PerformanceMetrics.calculate_annualized_return(
        initial_capital, final_capital, start_date, end_date
    )
    years = (end_date - start_date).days / 365
    cagr = PerformanceMetrics.calculate_cagr(initial_capital, final_capital, years)
    mdd_info = PerformanceMetrics.calculate_mdd(equity_curve)
    equity_df = pd.DataFrame(
        {
            "timestamp": [s.date for s in daily_stats],
            "equity": [float(s.equity) for s in daily_stats],
        }
    )
    volatility = PerformanceMetrics.calculate_volatility(equity_df)
    sharpe = PerformanceMetrics.calculate_sharpe_ratio(annualized_return, volatility)
    sortino = PerformanceMetrics.calculate_sortino_ratio(equity_df, annualized_return)
    calmar = PerformanceMetrics.calculate_calmar_ratio(annualized_return, mdd_info["mdd"])
    var_95 = PerformanceMetrics.calculate_var(equity_df)
    trade_stats = PerformanceMetrics.calculate_trade_count(completed_trades)
    win_rate = PerformanceMetrics.calculate_win_rate(completed_trades)
    profit_factor = PerformanceMetrics.calculate_profit_factor(completed_trades)
    avg_stats = PerformanceMetrics.calculate_avg_profit_loss(completed_trades)
    holding_stats = PerformanceMetrics.calculate_avg_holding_period(completed_trades)
    streak_stats = PerformanceMetrics.calculate_consecutive_wins_losses(completed_trades)
    return BacktestResultDTO(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        final_capital=final_capital,
        execution_timing=execution_timing,
        total_return=total_return,
        annualized_return=annualized_return,
        cagr=cagr,
        mdd=mdd_info["mdd"],
        volatility=volatility,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        calmar_ratio=calmar,
        var_95=var_95,
        total_trades=trade_stats["total"],
        winning_trades=trade_stats["wins"],
        losing_trades=trade_stats["losses"],
        win_rate=win_rate,
        profit_factor=profit_factor,
        avg_win=avg_stats["avg_win"],
        avg_loss=avg_stats["avg_loss"],
        avg_win_loss_ratio=avg_stats["avg_win_loss_ratio"],
        avg_holding_days=holding_stats["avg_days"],
        max_consecutive_wins=streak_stats["max_consecutive_wins"],
        max_consecutive_losses=streak_stats["max_consecutive_losses"],
        trades=trades,
        daily_stats=daily_stats,
    )
