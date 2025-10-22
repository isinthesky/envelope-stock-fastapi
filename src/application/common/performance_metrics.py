# -*- coding: utf-8 -*-
"""
Performance Metrics - 성과 지표 계산 모듈

백테스팅 결과의 수익률, 리스크, 거래 통계 등을 계산합니다.
"""

from datetime import datetime
from decimal import Decimal

import numpy as np
import pandas as pd


class PerformanceMetrics:
    """성과 지표 계산 유틸리티 클래스"""

    # ==================== 수익 지표 ====================

    @staticmethod
    def calculate_total_return(
        initial_capital: Decimal,
        final_capital: Decimal
    ) -> float:
        """
        총 수익률 계산

        Args:
            initial_capital: 초기 자본
            final_capital: 최종 자본

        Returns:
            float: 총 수익률 (%)
        """
        if initial_capital == 0:
            return 0.0

        total_return = (final_capital - initial_capital) / initial_capital * 100

        return float(total_return)

    @staticmethod
    def calculate_annualized_return(
        initial_capital: Decimal,
        final_capital: Decimal,
        start_date: datetime,
        end_date: datetime
    ) -> float:
        """
        연환산 수익률 계산

        Args:
            initial_capital: 초기 자본
            final_capital: 최종 자본
            start_date: 시작일
            end_date: 종료일

        Returns:
            float: 연환산 수익률 (%)
        """
        total_days = (end_date - start_date).days

        if total_days == 0 or initial_capital == 0:
            return 0.0

        # 연환산 계산
        annualized_return = (
            (float(final_capital / initial_capital)) ** (365 / total_days) - 1
        ) * 100

        return annualized_return

    @staticmethod
    def calculate_cagr(
        initial_capital: Decimal,
        final_capital: Decimal,
        years: float
    ) -> float:
        """
        CAGR (Compound Annual Growth Rate) 계산

        Args:
            initial_capital: 초기 자본
            final_capital: 최종 자본
            years: 연수

        Returns:
            float: CAGR (%)
        """
        if years <= 0 or initial_capital == 0:
            return 0.0

        cagr = (
            (float(final_capital / initial_capital)) ** (1 / years) - 1
        ) * 100

        return cagr

    @staticmethod
    def calculate_monthly_returns(equity_curve: pd.DataFrame) -> pd.Series:
        """
        월별 수익률 계산

        Args:
            equity_curve: 날짜별 자산 가치 DataFrame
                         (컬럼: timestamp, equity)

        Returns:
            pd.Series: 월별 수익률 (%)
        """
        # 월별 마지막 날 자산 가치
        equity_curve = equity_curve.copy()
        equity_curve["timestamp"] = pd.to_datetime(equity_curve["timestamp"])
        equity_curve = equity_curve.set_index("timestamp")

        monthly_equity = equity_curve["equity"].resample("M").last()

        # 월별 수익률
        monthly_returns = monthly_equity.pct_change() * 100

        return monthly_returns

    # ==================== 리스크 지표 ====================

    @staticmethod
    def calculate_mdd(equity_curve: list[Decimal]) -> dict:
        """
        MDD (Maximum Drawdown) 계산

        Args:
            equity_curve: 날짜별 자산 가치 리스트

        Returns:
            dict: MDD 정보
                - mdd: 최대 낙폭 (%)
                - peak_index: 고점 인덱스
                - valley_index: 저점 인덱스
                - recovery_days: 회복 기간 (일)
        """
        if not equity_curve:
            return {
                "mdd": 0.0,
                "peak_index": 0,
                "valley_index": 0,
                "recovery_days": 0
            }

        equity_array = np.array([float(e) for e in equity_curve])

        # 누적 최대값
        cummax = np.maximum.accumulate(equity_array)

        # 낙폭 계산
        drawdown = (equity_array - cummax) / cummax * 100

        # MDD
        mdd = float(drawdown.min())

        # MDD 발생 지점
        mdd_index = int(drawdown.argmin())
        peak_index = int(cummax[:mdd_index + 1].argmax()) if mdd_index > 0 else 0

        # 회복 기간
        recovery_days = len(equity_array) - mdd_index if mdd < -0.01 else 0

        return {
            "mdd": mdd,
            "peak_index": peak_index,
            "valley_index": mdd_index,
            "recovery_days": recovery_days
        }

    @staticmethod
    def calculate_volatility(equity_curve: pd.DataFrame) -> float:
        """
        연환산 변동성 계산

        Args:
            equity_curve: 날짜별 자산 가치 DataFrame
                         (컬럼: timestamp, equity)

        Returns:
            float: 연환산 변동성 (%)
        """
        if len(equity_curve) < 2:
            return 0.0

        # 일별 수익률
        daily_returns = equity_curve["equity"].pct_change().dropna()

        if len(daily_returns) == 0:
            return 0.0

        # 연환산 변동성 (252 거래일 기준)
        volatility = daily_returns.std() * np.sqrt(252) * 100

        return float(volatility)

    @staticmethod
    def calculate_sharpe_ratio(
        annualized_return: float,
        volatility: float,
        risk_free_rate: float = 3.0
    ) -> float:
        """
        Sharpe Ratio 계산

        Args:
            annualized_return: 연환산 수익률 (%)
            volatility: 연환산 변동성 (%)
            risk_free_rate: 무위험 이자율 (%)

        Returns:
            float: Sharpe Ratio
        """
        if volatility == 0:
            return 0.0

        sharpe = (annualized_return - risk_free_rate) / volatility

        return sharpe

    @staticmethod
    def calculate_sortino_ratio(
        equity_curve: pd.DataFrame,
        annualized_return: float,
        risk_free_rate: float = 3.0
    ) -> float:
        """
        Sortino Ratio 계산

        Args:
            equity_curve: 날짜별 자산 가치 DataFrame
            annualized_return: 연환산 수익률 (%)
            risk_free_rate: 무위험 이자율 (%)

        Returns:
            float: Sortino Ratio
        """
        if len(equity_curve) < 2:
            return 0.0

        # 일별 수익률
        daily_returns = equity_curve["equity"].pct_change().dropna()

        # 음수 수익률만 추출
        negative_returns = daily_returns[daily_returns < 0]

        if len(negative_returns) == 0:
            return 0.0

        # 하방 변동성
        downside_volatility = negative_returns.std() * np.sqrt(252) * 100

        if downside_volatility == 0:
            return 0.0

        sortino = (annualized_return - risk_free_rate) / downside_volatility

        return sortino

    @staticmethod
    def calculate_calmar_ratio(
        annualized_return: float,
        mdd: float
    ) -> float:
        """
        Calmar Ratio 계산

        Args:
            annualized_return: 연환산 수익률 (%)
            mdd: MDD (%)

        Returns:
            float: Calmar Ratio
        """
        if mdd >= 0:
            return 0.0

        calmar = annualized_return / abs(mdd)

        return calmar

    @staticmethod
    def calculate_var(
        equity_curve: pd.DataFrame,
        confidence_level: float = 0.95
    ) -> float:
        """
        Historical VaR (Value at Risk) 계산

        Args:
            equity_curve: 날짜별 자산 가치 DataFrame
            confidence_level: 신뢰수준 (기본 95%)

        Returns:
            float: VaR (%)
        """
        if len(equity_curve) < 2:
            return 0.0

        # 일별 수익률
        daily_returns = equity_curve["equity"].pct_change().dropna()

        if len(daily_returns) == 0:
            return 0.0

        # VaR
        var = daily_returns.quantile(1 - confidence_level) * 100

        return float(var)

    # ==================== 거래 통계 ====================

    @staticmethod
    def calculate_trade_count(trades: list[dict]) -> dict:
        """
        거래 통계

        Args:
            trades: 거래 내역 리스트
                   [{"profit_rate": 0.05, ...}, ...]

        Returns:
            dict: 거래 통계
        """
        if not trades:
            return {
                "total": 0,
                "wins": 0,
                "losses": 0,
                "breakeven": 0
            }

        total = len(trades)
        wins = sum(1 for t in trades if t.get("profit_rate", 0) > 0)
        losses = sum(1 for t in trades if t.get("profit_rate", 0) < 0)
        breakeven = total - wins - losses

        return {
            "total": total,
            "wins": wins,
            "losses": losses,
            "breakeven": breakeven
        }

    @staticmethod
    def calculate_win_rate(trades: list[dict]) -> float:
        """
        승률 계산

        Args:
            trades: 거래 내역

        Returns:
            float: 승률 (%)
        """
        if not trades:
            return 0.0

        wins = sum(1 for t in trades if t.get("profit_rate", 0) > 0)
        win_rate = wins / len(trades) * 100

        return win_rate

    @staticmethod
    def calculate_profit_factor(trades: list[dict]) -> float:
        """
        Profit Factor 계산

        Args:
            trades: 거래 내역

        Returns:
            float: Profit Factor
        """
        if not trades:
            return 0.0

        total_profit = sum(
            t.get("profit_rate", 0)
            for t in trades
            if t.get("profit_rate", 0) > 0
        )
        total_loss = abs(
            sum(
                t.get("profit_rate", 0)
                for t in trades
                if t.get("profit_rate", 0) < 0
            )
        )

        if total_loss == 0:
            return float('inf') if total_profit > 0 else 0.0

        profit_factor = total_profit / total_loss

        return profit_factor

    @staticmethod
    def calculate_avg_profit_loss(trades: list[dict]) -> dict:
        """
        평균 수익/손실 계산

        Args:
            trades: 거래 내역

        Returns:
            dict: 평균 수익/손실 통계
        """
        if not trades:
            return {
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "avg_win_loss_ratio": 0.0
            }

        winning_trades = [
            t["profit_rate"] for t in trades if t.get("profit_rate", 0) > 0
        ]
        losing_trades = [
            t["profit_rate"] for t in trades if t.get("profit_rate", 0) < 0
        ]

        avg_win = sum(winning_trades) / len(winning_trades) if winning_trades else 0.0
        avg_loss = sum(losing_trades) / len(losing_trades) if losing_trades else 0.0

        avg_win_loss_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0.0

        return {
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "avg_win_loss_ratio": avg_win_loss_ratio
        }

    @staticmethod
    def calculate_avg_holding_period(trades: list[dict]) -> dict:
        """
        평균 보유 기간 계산

        Args:
            trades: 거래 내역
                   [{"holding_days": 5, ...}, ...]

        Returns:
            dict: 평균 보유 기간 통계
        """
        if not trades:
            return {
                "avg_days": 0.0,
                "max_days": 0,
                "min_days": 0
            }

        holding_periods = [
            t.get("holding_days", 0) for t in trades if "holding_days" in t
        ]

        if not holding_periods:
            return {
                "avg_days": 0.0,
                "max_days": 0,
                "min_days": 0
            }

        return {
            "avg_days": sum(holding_periods) / len(holding_periods),
            "max_days": max(holding_periods),
            "min_days": min(holding_periods)
        }

    @staticmethod
    def calculate_consecutive_wins_losses(trades: list[dict]) -> dict:
        """
        연속 승/패 기록

        Args:
            trades: 거래 내역

        Returns:
            dict: 연속 승/패 통계
        """
        if not trades:
            return {
                "max_consecutive_wins": 0,
                "max_consecutive_losses": 0,
                "current_streak": 0
            }

        max_wins = 0
        max_losses = 0
        current_wins = 0
        current_losses = 0

        for trade in trades:
            profit_rate = trade.get("profit_rate", 0)

            if profit_rate > 0:
                current_wins += 1
                current_losses = 0
                max_wins = max(max_wins, current_wins)
            elif profit_rate < 0:
                current_losses += 1
                current_wins = 0
                max_losses = max(max_losses, current_losses)

        # 현재 연속 기록
        current_streak = current_wins if current_wins > 0 else -current_losses

        return {
            "max_consecutive_wins": max_wins,
            "max_consecutive_losses": max_losses,
            "current_streak": current_streak
        }

    # ==================== 벤치마크 비교 ====================

    @staticmethod
    def calculate_alpha(
        strategy_return: float,
        market_return: float,
        beta: float,
        risk_free_rate: float = 3.0
    ) -> float:
        """
        Alpha 계산

        Args:
            strategy_return: 전략 수익률 (%)
            market_return: 시장 수익률 (%)
            beta: 베타 계수
            risk_free_rate: 무위험 이자율 (%)

        Returns:
            float: Alpha (%)
        """
        expected_return = risk_free_rate + beta * (market_return - risk_free_rate)
        alpha = strategy_return - expected_return

        return alpha

    @staticmethod
    def calculate_beta(
        strategy_returns: pd.Series,
        market_returns: pd.Series
    ) -> float:
        """
        Beta 계산

        Args:
            strategy_returns: 전략 일별 수익률
            market_returns: 시장 일별 수익률

        Returns:
            float: Beta
        """
        if len(strategy_returns) < 2 or len(market_returns) < 2:
            return 0.0

        # 공분산
        covariance = strategy_returns.cov(market_returns)

        # 시장 분산
        market_variance = market_returns.var()

        if market_variance == 0:
            return 0.0

        beta = covariance / market_variance

        return float(beta)

    @staticmethod
    def calculate_tracking_error(
        strategy_returns: pd.Series,
        benchmark_returns: pd.Series
    ) -> float:
        """
        Tracking Error 계산

        Args:
            strategy_returns: 전략 일별 수익률
            benchmark_returns: 벤치마크 일별 수익률

        Returns:
            float: Tracking Error (%)
        """
        if len(strategy_returns) < 2 or len(benchmark_returns) < 2:
            return 0.0

        # 초과 수익률
        excess_returns = strategy_returns - benchmark_returns

        # 연환산 표준편차
        tracking_error = excess_returns.std() * np.sqrt(252) * 100

        return float(tracking_error)

    @staticmethod
    def calculate_information_ratio(
        strategy_return: float,
        benchmark_return: float,
        tracking_error: float
    ) -> float:
        """
        Information Ratio 계산

        Args:
            strategy_return: 전략 수익률 (%)
            benchmark_return: 벤치마크 수익률 (%)
            tracking_error: Tracking Error (%)

        Returns:
            float: Information Ratio
        """
        if tracking_error == 0:
            return 0.0

        ir = (strategy_return - benchmark_return) / tracking_error

        return ir
