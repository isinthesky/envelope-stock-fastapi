# -*- coding: utf-8 -*-
"""
Performance Metrics - 성과 지표 계산 모듈

백테스팅 결과의 수익률, 리스크, 거래 통계 등을 계산합니다.
"""

from datetime import datetime
from decimal import Decimal

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252


class PerformanceMetrics:
    """성과 지표 계산 유틸리티 클래스"""

    # ==================== 수익 지표 ====================

    @staticmethod
    def calculate_total_return(initial_capital: Decimal, final_capital: Decimal) -> float:
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
        initial_capital: Decimal, final_capital: Decimal, start_date: datetime, end_date: datetime
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
    def calculate_cagr(initial_capital: Decimal, final_capital: Decimal, years: float) -> float:
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

        cagr = ((float(final_capital / initial_capital)) ** (1 / years) - 1) * 100

        return cagr

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
                - recovery_days: MDD 저점 → 직전 고점 회복까지 걸린 **관측 바(거래일) 수**.
                  기간 내 미회복이면 None, 낙폭이 사실상 없으면(>-0.01%) 0.
        """
        if not equity_curve:
            return {"mdd": 0.0, "peak_index": 0, "valley_index": 0, "recovery_days": 0}

        equity_array = np.array([float(e) for e in equity_curve])

        # 누적 최대값
        cummax = np.maximum.accumulate(equity_array)

        # 낙폭 계산
        drawdown = (equity_array - cummax) / cummax * 100

        # MDD
        mdd = float(drawdown.min())

        # MDD 발생 지점
        mdd_index = int(drawdown.argmin())
        peak_index = int(cummax[: mdd_index + 1].argmax()) if mdd_index > 0 else 0

        # 회복 기간: 저점 이후 처음으로 직전 고점(peak) 이상을 회복한 바까지의 거리.
        # (이전 구현은 "저점~데이터 끝" 길이라 회복 여부와 무관한 값이었다.)
        recovery_days: int | None = 0
        if mdd < -0.01:
            peak_value = cummax[mdd_index]
            recovered = np.nonzero(equity_array[mdd_index + 1 :] >= peak_value)[0]
            recovery_days = int(recovered[0]) + 1 if recovered.size else None

        return {
            "mdd": mdd,
            "peak_index": peak_index,
            "valley_index": mdd_index,
            "recovery_days": recovery_days,
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
    def daily_risk_free_rate(risk_free_rate: float = 3.0) -> float:
        """연 무위험이자율(%)을 일별(252 거래일) 복리 등가 수익률(소수)로 변환."""
        return (1.0 + risk_free_rate / 100.0) ** (1.0 / TRADING_DAYS_PER_YEAR) - 1.0

    @staticmethod
    def _daily_returns(equity_curve: pd.DataFrame) -> pd.Series:
        if len(equity_curve) < 2:
            return pd.Series(dtype=float)
        return equity_curve["equity"].astype(float).pct_change().dropna()

    @staticmethod
    def calculate_daily_sharpe_ratio(
        equity_curve: pd.DataFrame,
        risk_free_rate: float = 3.0,
    ) -> float:
        """연환산 Sharpe = mean(일별 초과수익) / std(일별 수익) × √252.

        - 일별 초과수익 = r_t − rf_daily, rf_daily = (1+rf)^(1/252) − 1
        - std는 표본표준편차(ddof=1) — `statistics.sharpe_stats`(DSR)와 같은 정의다.
        - ``risk_free_rate=0.0``이면 DSR의 per-period Sharpe × √252 와 동일 기준.

        Args:
            equity_curve: (timestamp, equity) DataFrame
            risk_free_rate: 연 무위험이자율 (%) — 기본 3.0
        """
        returns = PerformanceMetrics._daily_returns(equity_curve)
        if len(returns) < 2:
            return 0.0
        sd = float(returns.std(ddof=1))
        if sd == 0.0 or sd != sd:
            return 0.0
        excess = returns - PerformanceMetrics.daily_risk_free_rate(risk_free_rate)
        return float(excess.mean() / sd * np.sqrt(TRADING_DAYS_PER_YEAR))

    @staticmethod
    def calculate_sharpe_ratio(
        annualized_return: float, volatility: float, risk_free_rate: float = 3.0
    ) -> float:
        """
        (레거시) CAGR 기반 Sharpe = (연환산수익률 − rf) / 연환산변동성.

        ⚠️ 기하평균(CAGR)과 산술 변동성을 섞은 비표준 정의라 DSR(일별 Sharpe)과
        일관되지 않는다. 백테스트 결과/walk-forward는 `calculate_daily_sharpe_ratio`
        를 사용한다. 하위호환용으로만 유지.

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
        annualized_return: float | None = None,
        risk_free_rate: float = 3.0,
    ) -> float:
        """
        Sortino Ratio (표준 정의, target = 일별 무위험이자율)

            DD = sqrt( mean_t( min(r_t − target, 0)^2 ) )   ← **전체 관측치** 기준
            Sortino = mean(r_t − target) / DD × √252

        이전 구현은 "음수 수익만의 표준편차"를 써서 하방편차를 잘못 계산했다.

        Args:
            equity_curve: 날짜별 자산 가치 DataFrame
            annualized_return: (미사용, 하위호환 인자) 분자는 일별 초과수익 평균으로
                계산해 Sharpe와 같은 기준을 쓴다.
            risk_free_rate: 연 무위험 이자율 (%) — target으로 사용

        Returns:
            float: Sortino Ratio (하방 편차 0이면 0.0)
        """
        _ = annualized_return
        returns = PerformanceMetrics._daily_returns(equity_curve)
        if len(returns) < 2:
            return 0.0
        excess = returns.to_numpy(dtype=float) - PerformanceMetrics.daily_risk_free_rate(
            risk_free_rate
        )
        downside = np.minimum(excess, 0.0)
        downside_dev = float(np.sqrt(np.mean(downside**2)))
        if downside_dev == 0.0:
            return 0.0
        return float(excess.mean() / downside_dev * np.sqrt(TRADING_DAYS_PER_YEAR))

    @staticmethod
    def calculate_calmar_ratio(annualized_return: float, mdd: float) -> float:
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
    def calculate_var(equity_curve: pd.DataFrame, confidence_level: float = 0.95) -> float:
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
            return {"total": 0, "wins": 0, "losses": 0, "breakeven": 0}

        total = len(trades)
        wins = sum(1 for t in trades if t.get("profit_rate", 0) > 0)
        losses = sum(1 for t in trades if t.get("profit_rate", 0) < 0)
        breakeven = total - wins - losses

        return {"total": total, "wins": wins, "losses": losses, "breakeven": breakeven}

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
        Profit Factor = 총이익(금액) / 총손실(금액)

        모든 거래에 ``profit``(KRW, 비용 차감 후 손익)이 있으면 **금액 기준**으로
        계산한다. 수익률 합 기준은 포지션 크기를 무시해 왜곡되므로, ``profit`` 이
        없는 레거시 입력에서만 ``profit_rate`` 합으로 폴백한다.

        Args:
            trades: 거래 내역 ({"profit": Decimal|float, "profit_rate": float, ...})

        Returns:
            float: Profit Factor
        """
        if not trades:
            return 0.0

        key = "profit" if all(t.get("profit") is not None for t in trades) else "profit_rate"
        values = [float(t.get(key) or 0) for t in trades]
        total_profit = sum(v for v in values if v > 0)
        total_loss = abs(sum(v for v in values if v < 0))

        if total_loss == 0:
            # JSON 직렬화 가능하도록 큰 값 반환 (inf 대신)
            return 9999.99 if total_profit > 0 else 0.0

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
            return {"avg_win": 0.0, "avg_loss": 0.0, "avg_win_loss_ratio": 0.0}

        winning_trades = [t["profit_rate"] for t in trades if t.get("profit_rate", 0) > 0]
        losing_trades = [t["profit_rate"] for t in trades if t.get("profit_rate", 0) < 0]

        avg_win = sum(winning_trades) / len(winning_trades) if winning_trades else 0.0
        avg_loss = sum(losing_trades) / len(losing_trades) if losing_trades else 0.0

        avg_win_loss_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0.0

        return {"avg_win": avg_win, "avg_loss": avg_loss, "avg_win_loss_ratio": avg_win_loss_ratio}

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
            return {"avg_days": 0.0, "max_days": 0, "min_days": 0}

        holding_periods = [t.get("holding_days", 0) for t in trades if "holding_days" in t]

        if not holding_periods:
            return {"avg_days": 0.0, "max_days": 0, "min_days": 0}

        return {
            "avg_days": sum(holding_periods) / len(holding_periods),
            "max_days": max(holding_periods),
            "min_days": min(holding_periods),
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
            return {"max_consecutive_wins": 0, "max_consecutive_losses": 0, "current_streak": 0}

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
            "current_streak": current_streak,
        }

    # ==================== 벤치마크 비교 ====================
