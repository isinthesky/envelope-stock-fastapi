# -*- coding: utf-8 -*-
"""
골든크로스 전략 백테스팅

analysis_history 테이블의 종목들에 대해 2년치 일봉 데이터로
골든크로스 매수/매도 전략을 백테스팅합니다.

전략 규칙:
- 매수: MA55가 MA165를 상향 돌파 (골든크로스) + Stochastic K < 30 (과매도)
- 매도: MA55가 MA165를 하향 돌파 (데드크로스) 또는 손절/익절
"""

import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pandas as pd

from src.adapters.cache.redis_client import get_redis_client
from src.adapters.database.connection import get_db
from src.adapters.external.kis_api.client import KISAPIClient
from src.application.common.indicators import TechnicalIndicators
from src.application.domain.backtest.cost_schedule import get_backtest_cost_schedule
from src.application.domain.backtest.data_loader import BacktestDataLoader
from src.application.domain.market_data.service import MarketDataService


@dataclass
class GoldenCrossConfig:
    """골든크로스 전략 설정"""

    short_ma_period: int = 55  # 단기 이동평균 기간
    long_ma_period: int = 165  # 장기 이동평균 기간
    stoch_k_period: int = 14  # Stochastic K 기간
    stoch_d_period: int = 3  # Stochastic D 기간
    stoch_oversold: float = 30.0  # 과매도 임계값
    stoch_overbought: float = 70.0  # 과매수 임계값
    stop_loss_ratio: float = -0.07  # 손절 비율 (-7%)
    take_profit_ratio: float = 0.15  # 익절 비율 (+15%)
    allocation_ratio: float = 0.95  # 자본 배분 비율


@dataclass
class BacktestConfig:
    """백테스트 설정"""

    initial_capital: Decimal = Decimal("10_000_000")  # 초기 자본 1,000만원
    cost_schedule_date: date = date(2025, 1, 1)
    commission_rate: float | None = None
    tax_rate: float | None = None
    slippage_rate: float | None = None
    cost_source_label: str = ""

    def __post_init__(self) -> None:
        schedule = get_backtest_cost_schedule(self.cost_schedule_date)
        if self.commission_rate is None:
            self.commission_rate = float(schedule.default_commission_rate)
        if self.tax_rate is None:
            self.tax_rate = float(schedule.sell_tax_rate)
        if self.slippage_rate is None:
            self.slippage_rate = float(schedule.default_slippage_rate)
        self.cost_source_label = schedule.source_label


@dataclass
class Trade:
    """거래 기록"""

    trade_id: int
    entry_date: datetime
    entry_price: Decimal
    quantity: int
    exit_date: datetime | None = None
    exit_price: Decimal | None = None
    exit_reason: str | None = None
    profit_loss: Decimal = Decimal("0")
    profit_rate: float = 0.0
    holding_days: int = 0


@dataclass
class BacktestResult:
    """백테스트 결과"""

    symbol: str
    name: str
    start_date: datetime
    end_date: datetime
    initial_capital: Decimal
    final_capital: Decimal
    total_return: float
    annualized_return: float
    mdd: float
    mdd_start_date: datetime | None
    mdd_end_date: datetime | None
    sharpe_ratio: float
    win_rate: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    avg_profit: float
    avg_loss: float
    profit_factor: float
    avg_holding_days: float
    max_consecutive_wins: int
    max_consecutive_losses: int
    trades: list[Trade] = field(default_factory=list)
    daily_equity: list[dict] = field(default_factory=list)
    error: str | None = None


class GoldenCrossBacktester:
    """골든크로스 전략 백테스터"""

    def __init__(
        self,
        strategy_config: GoldenCrossConfig,
        backtest_config: BacktestConfig,
    ):
        self.strategy_config = strategy_config
        self.backtest_config = backtest_config

    async def run(
        self,
        symbol: str,
        name: str,
        df: pd.DataFrame,
        start_date: datetime,
        end_date: datetime,
    ) -> BacktestResult:
        """백테스트 실행"""
        # 초기화
        cash = self.backtest_config.initial_capital
        position_quantity = 0
        position_entry_price = Decimal("0")
        position_entry_date: datetime | None = None
        trade_id = 0

        trades: list[Trade] = []
        current_trade: Trade | None = None
        daily_equity: list[dict] = []
        equity_curve: list[Decimal] = []

        # 지표 계산
        df = TechnicalIndicators.prepare_golden_cross_indicators(
            df,
            short_ma_period=self.strategy_config.short_ma_period,
            long_ma_period=self.strategy_config.long_ma_period,
            stoch_k_period=self.strategy_config.stoch_k_period,
            stoch_d_period=self.strategy_config.stoch_d_period,
        )

        # 최소 기간 데이터 확인
        min_period = self.strategy_config.long_ma_period
        if len(df) < min_period:
            return BacktestResult(
                symbol=symbol,
                name=name,
                start_date=start_date,
                end_date=end_date,
                initial_capital=self.backtest_config.initial_capital,
                final_capital=self.backtest_config.initial_capital,
                total_return=0.0,
                annualized_return=0.0,
                mdd=0.0,
                mdd_start_date=None,
                mdd_end_date=None,
                sharpe_ratio=0.0,
                win_rate=0.0,
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                avg_profit=0.0,
                avg_loss=0.0,
                profit_factor=0.0,
                avg_holding_days=0.0,
                max_consecutive_wins=0,
                max_consecutive_losses=0,
                error=f"Insufficient data: {len(df)} rows (minimum {min_period} required)",
            )

        # 일별 처리
        for idx, row in df.iterrows():
            current_date = row["timestamp"]
            current_price = Decimal(str(row["close"]))
            ma_short = row["ma_short"]
            ma_long = row["ma_long"]
            stoch_k = row["stoch_k"]
            gc_signal = row["gc_signal"]  # 골든크로스 발생
            dc_signal = row["dc_signal"]  # 데드크로스 발생
            is_gc_active = row["is_gc_active"]  # 골든크로스 활성 상태

            # NaN 체크
            if pd.isna(ma_short) or pd.isna(ma_long):
                # 자산 기록 (포지션 없을 때)
                position_value = (
                    position_quantity * current_price if position_quantity > 0 else Decimal("0")
                )
                equity = cash + position_value
                equity_curve.append(equity)
                daily_equity.append(
                    {
                        "date": current_date,
                        "equity": float(equity),
                        "cash": float(cash),
                        "position_value": float(position_value),
                    }
                )
                continue

            # === 1. 손절/익절 체크 (포지션 보유 시) ===
            if position_quantity > 0 and current_trade:
                profit_rate = float((current_price - position_entry_price) / position_entry_price)

                # 손절
                if profit_rate <= self.strategy_config.stop_loss_ratio:
                    cash, current_trade = self._execute_sell(
                        cash,
                        current_price,
                        position_quantity,
                        position_entry_price,
                        position_entry_date,
                        current_date,
                        current_trade,
                        "stop_loss",
                    )
                    trades.append(current_trade)
                    position_quantity = 0
                    current_trade = None

                # 익절
                elif profit_rate >= self.strategy_config.take_profit_ratio:
                    cash, current_trade = self._execute_sell(
                        cash,
                        current_price,
                        position_quantity,
                        position_entry_price,
                        position_entry_date,
                        current_date,
                        current_trade,
                        "take_profit",
                    )
                    trades.append(current_trade)
                    position_quantity = 0
                    current_trade = None

            # === 2. 매매 시그널 처리 ===
            # 매수 조건: 골든크로스 활성 + Stochastic 과매도
            if position_quantity == 0:
                # 방법 1: 골든크로스 발생 시점 매수
                # if gc_signal and stoch_k < self.strategy_config.stoch_oversold:

                # 방법 2: 골든크로스 활성 상태에서 과매도 시 매수
                if is_gc_active and stoch_k < self.strategy_config.stoch_oversold:
                    trade_id += 1
                    quantity = self._calculate_position_size(cash, current_price)

                    if quantity > 0:
                        # 매수 실행
                        buy_cost = current_price * quantity
                        commission = buy_cost * Decimal(str(self.backtest_config.commission_rate))
                        slippage = buy_cost * Decimal(str(self.backtest_config.slippage_rate))
                        total_cost = buy_cost + commission + slippage

                        if total_cost <= cash:
                            cash -= total_cost
                            position_quantity = quantity
                            position_entry_price = current_price
                            position_entry_date = current_date

                            current_trade = Trade(
                                trade_id=trade_id,
                                entry_date=current_date,
                                entry_price=current_price,
                                quantity=quantity,
                            )

            # 매도 조건: 데드크로스 발생
            elif position_quantity > 0 and current_trade:
                if dc_signal:
                    cash, current_trade = self._execute_sell(
                        cash,
                        current_price,
                        position_quantity,
                        position_entry_price,
                        position_entry_date,
                        current_date,
                        current_trade,
                        "death_cross",
                    )
                    trades.append(current_trade)
                    position_quantity = 0
                    current_trade = None

            # === 3. 일별 자산 기록 ===
            position_value = (
                position_quantity * current_price if position_quantity > 0 else Decimal("0")
            )
            equity = cash + position_value
            equity_curve.append(equity)
            daily_equity.append(
                {
                    "date": current_date,
                    "equity": float(equity),
                    "cash": float(cash),
                    "position_value": float(position_value),
                }
            )

        # 마지막 포지션 청산
        if position_quantity > 0 and current_trade:
            last_price = Decimal(str(df.iloc[-1]["close"]))
            last_date = df.iloc[-1]["timestamp"]
            cash, current_trade = self._execute_sell(
                cash,
                last_price,
                position_quantity,
                position_entry_price,
                position_entry_date,
                last_date,
                current_trade,
                "end_of_period",
            )
            trades.append(current_trade)

        # 결과 계산
        final_capital = equity_curve[-1] if equity_curve else self.backtest_config.initial_capital
        result = self._calculate_result(
            symbol, name, start_date, end_date, final_capital, trades, equity_curve, daily_equity
        )

        return result

    def _calculate_position_size(self, cash: Decimal, price: Decimal) -> int:
        """포지션 크기 계산"""
        if price <= 0:
            return 0
        target_amount = cash * Decimal(str(self.strategy_config.allocation_ratio))
        quantity = int(target_amount / price)
        return quantity

    def _execute_sell(
        self,
        cash: Decimal,
        price: Decimal,
        quantity: int,
        entry_price: Decimal,
        entry_date: datetime | None,
        exit_date: datetime,
        trade: Trade,
        exit_reason: str,
    ) -> tuple[Decimal, Trade]:
        """매도 실행"""
        sell_amount = price * quantity
        commission = sell_amount * Decimal(str(self.backtest_config.commission_rate))
        tax = sell_amount * Decimal(str(self.backtest_config.tax_rate))
        slippage = sell_amount * Decimal(str(self.backtest_config.slippage_rate))
        net_proceeds = sell_amount - commission - tax - slippage

        cash += net_proceeds

        profit_loss = (price - entry_price) * quantity - commission - tax - slippage
        profit_rate = float((price - entry_price) / entry_price) if entry_price > 0 else 0.0
        holding_days = (exit_date - entry_date).days if entry_date else 0

        trade.exit_date = exit_date
        trade.exit_price = price
        trade.exit_reason = exit_reason
        trade.profit_loss = profit_loss
        trade.profit_rate = profit_rate * 100  # 퍼센트로 변환
        trade.holding_days = holding_days

        return cash, trade

    def _calculate_result(
        self,
        symbol: str,
        name: str,
        start_date: datetime,
        end_date: datetime,
        final_capital: Decimal,
        trades: list[Trade],
        equity_curve: list[Decimal],
        daily_equity: list[dict],
    ) -> BacktestResult:
        """결과 계산"""
        initial_capital = self.backtest_config.initial_capital

        # 수익률 계산
        total_return = float((final_capital - initial_capital) / initial_capital * 100)

        # 연환산 수익률
        years = (end_date - start_date).days / 365
        if years > 0 and final_capital > 0:
            annualized_return = (float(final_capital / initial_capital) ** (1 / years) - 1) * 100
        else:
            annualized_return = 0.0

        # MDD 계산
        mdd, mdd_start, mdd_end = self._calculate_mdd(equity_curve, daily_equity)

        # Sharpe Ratio 계산 (간이 버전)
        if len(daily_equity) > 1:
            returns = []
            for i in range(1, len(daily_equity)):
                prev_eq = daily_equity[i - 1]["equity"]
                curr_eq = daily_equity[i]["equity"]
                if prev_eq > 0:
                    returns.append((curr_eq - prev_eq) / prev_eq)
            if returns:
                avg_return = sum(returns) / len(returns)
                std_return = (sum((r - avg_return) ** 2 for r in returns) / len(returns)) ** 0.5
                sharpe_ratio = (
                    (avg_return * 252 / (std_return * (252**0.5))) if std_return > 0 else 0.0
                )
            else:
                sharpe_ratio = 0.0
        else:
            sharpe_ratio = 0.0

        # 거래 통계
        completed_trades = [t for t in trades if t.exit_date is not None]
        winning_trades = [t for t in completed_trades if t.profit_rate > 0]
        losing_trades = [t for t in completed_trades if t.profit_rate <= 0]

        win_rate = (len(winning_trades) / len(completed_trades) * 100) if completed_trades else 0.0

        avg_profit = (
            sum(t.profit_rate for t in winning_trades) / len(winning_trades)
            if winning_trades
            else 0.0
        )
        avg_loss = (
            sum(t.profit_rate for t in losing_trades) / len(losing_trades) if losing_trades else 0.0
        )

        total_profit = sum(float(t.profit_loss) for t in winning_trades) if winning_trades else 0.0
        total_loss = abs(sum(float(t.profit_loss) for t in losing_trades)) if losing_trades else 0.0
        profit_factor = (
            total_profit / total_loss
            if total_loss > 0
            else (float("inf") if total_profit > 0 else 0.0)
        )

        avg_holding_days = (
            sum(t.holding_days for t in completed_trades) / len(completed_trades)
            if completed_trades
            else 0.0
        )

        # 연승/연패
        max_wins, max_losses = self._calculate_streaks(completed_trades)

        return BacktestResult(
            symbol=symbol,
            name=name,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            final_capital=final_capital,
            total_return=total_return,
            annualized_return=annualized_return,
            mdd=mdd,
            mdd_start_date=mdd_start,
            mdd_end_date=mdd_end,
            sharpe_ratio=sharpe_ratio,
            win_rate=win_rate,
            total_trades=len(completed_trades),
            winning_trades=len(winning_trades),
            losing_trades=len(losing_trades),
            avg_profit=avg_profit,
            avg_loss=avg_loss,
            profit_factor=profit_factor,
            avg_holding_days=avg_holding_days,
            max_consecutive_wins=max_wins,
            max_consecutive_losses=max_losses,
            trades=trades,
            daily_equity=daily_equity,
        )

    def _calculate_mdd(
        self,
        equity_curve: list[Decimal],
        daily_equity: list[dict],
    ) -> tuple[float, datetime | None, datetime | None]:
        """MDD 계산"""
        if not equity_curve:
            return 0.0, None, None

        peak = equity_curve[0]
        mdd = 0.0
        mdd_start = None
        mdd_end = None
        current_peak_idx = 0

        for idx, equity in enumerate(equity_curve):
            if equity > peak:
                peak = equity
                current_peak_idx = idx

            drawdown = float((peak - equity) / peak * 100) if peak > 0 else 0.0

            if drawdown > mdd:
                mdd = drawdown
                mdd_start = (
                    daily_equity[current_peak_idx]["date"]
                    if current_peak_idx < len(daily_equity)
                    else None
                )
                mdd_end = daily_equity[idx]["date"] if idx < len(daily_equity) else None

        return mdd, mdd_start, mdd_end

    def _calculate_streaks(self, trades: list[Trade]) -> tuple[int, int]:
        """연승/연패 계산"""
        if not trades:
            return 0, 0

        max_wins = 0
        max_losses = 0
        current_wins = 0
        current_losses = 0

        for trade in trades:
            if trade.profit_rate > 0:
                current_wins += 1
                current_losses = 0
                max_wins = max(max_wins, current_wins)
            else:
                current_losses += 1
                current_wins = 0
                max_losses = max(max_losses, current_losses)

        return max_wins, max_losses


async def get_analysis_history_symbols(db_session) -> list[dict]:
    """analysis_history 테이블에서 활성 종목 조회"""
    from sqlalchemy import text

    query = text(
        """
        SELECT DISTINCT symbol, name, analysis_type
        FROM analysis_history
        WHERE is_active = true
        ORDER BY symbol
    """
    )

    result = await db_session.execute(query)
    rows = result.fetchall()

    return [{"symbol": row[0], "name": row[1], "analysis_type": row[2]} for row in rows]


def generate_report(results: list[BacktestResult], report_path: str) -> str:
    """리포트 생성"""
    from datetime import datetime as dt

    lines = []
    lines.append("# 골든크로스 전략 백테스트 리포트")
    lines.append("")
    lines.append(f"> 생성일시: {dt.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")

    # 요약
    lines.append("## 1. 요약")
    lines.append("")
    lines.append("### 백테스트 설정")
    lines.append("- **전략**: 골든크로스 (MA55/MA165)")
    lines.append("- **기간**: 최근 2년")
    lines.append("- **초기 자본**: 10,000,000원")
    lines.append("- **매수 조건**: MA55 > MA165 (골든크로스 활성) + Stochastic K < 30 (과매도)")
    lines.append("- **매도 조건**: MA55 < MA165 (데드크로스) 또는 손절(-7%)/익절(+15%)")
    lines.append("")

    valid_results = [r for r in results if r.error is None]
    error_results = [r for r in results if r.error is not None]

    lines.append(f"### 테스트 종목: {len(results)}개")
    lines.append(f"- 성공: {len(valid_results)}개")
    lines.append(f"- 실패: {len(error_results)}개")
    lines.append("")

    if valid_results:
        avg_return = sum(r.total_return for r in valid_results) / len(valid_results)
        avg_mdd = sum(r.mdd for r in valid_results) / len(valid_results)
        avg_win_rate = sum(r.win_rate for r in valid_results) / len(valid_results)
        total_trades = sum(r.total_trades for r in valid_results)

        lines.append("### 전체 성과 요약")
        lines.append(f"- **평균 수익률**: {avg_return:.2f}%")
        lines.append(f"- **평균 MDD**: {avg_mdd:.2f}%")
        lines.append(f"- **평균 승률**: {avg_win_rate:.1f}%")
        lines.append(f"- **총 거래 횟수**: {total_trades}회")
        lines.append("")

    # 종목별 상세 결과
    lines.append("## 2. 종목별 상세 결과")
    lines.append("")

    if valid_results:
        # 수익률 기준 정렬
        sorted_results = sorted(valid_results, key=lambda x: x.total_return, reverse=True)

        lines.append("### 수익률 순위")
        lines.append("")
        lines.append("| 순위 | 종목 | 수익률 | MDD | 승률 | 거래수 | Sharpe | 평균보유 |")
        lines.append("|:----:|:-----|-------:|----:|-----:|-------:|-------:|--------:|")

        for idx, r in enumerate(sorted_results, 1):
            emoji = "🥇" if idx == 1 else ("🥈" if idx == 2 else ("🥉" if idx == 3 else f"{idx}"))
            lines.append(
                f"| {emoji} | {r.name} ({r.symbol}) | {r.total_return:+.2f}% | "
                f"{r.mdd:.2f}% | {r.win_rate:.1f}% | {r.total_trades} | "
                f"{r.sharpe_ratio:.2f} | {r.avg_holding_days:.0f}일 |"
            )

        lines.append("")

        # 각 종목 상세
        for r in sorted_results:
            lines.append(f"### {r.name} ({r.symbol})")
            lines.append("")
            lines.append(
                f"**기간**: {r.start_date.strftime('%Y-%m-%d')} ~ {r.end_date.strftime('%Y-%m-%d')}"
            )
            lines.append("")
            lines.append("#### 수익 지표")
            lines.append(f"- 초기 자본: {r.initial_capital:,.0f}원")
            lines.append(f"- 최종 자본: {r.final_capital:,.0f}원")
            lines.append(f"- **총 수익률**: {r.total_return:+.2f}%")
            lines.append(f"- **연환산 수익률**: {r.annualized_return:+.2f}%")
            lines.append("")
            lines.append("#### 리스크 지표")
            lines.append(f"- **MDD**: {r.mdd:.2f}%")
            if r.mdd_start_date and r.mdd_end_date:
                lines.append(
                    f"  - 기간: {r.mdd_start_date.strftime('%Y-%m-%d')} ~ {r.mdd_end_date.strftime('%Y-%m-%d')}"
                )
            lines.append(f"- **Sharpe Ratio**: {r.sharpe_ratio:.2f}")
            lines.append("")
            lines.append("#### 거래 통계")
            lines.append(
                f"- 총 거래: {r.total_trades}회 (승리: {r.winning_trades}, 패배: {r.losing_trades})"
            )
            lines.append(f"- **승률**: {r.win_rate:.1f}%")
            lines.append(f"- 평균 수익: {r.avg_profit:+.2f}%")
            lines.append(f"- 평균 손실: {r.avg_loss:.2f}%")
            lines.append(f"- **Profit Factor**: {r.profit_factor:.2f}")
            lines.append(f"- 평균 보유 기간: {r.avg_holding_days:.0f}일")
            lines.append(
                f"- 최대 연승: {r.max_consecutive_wins}회, 최대 연패: {r.max_consecutive_losses}회"
            )
            lines.append("")

            # 거래 내역
            if r.trades:
                lines.append("#### 거래 내역")
                lines.append("")
                lines.append("| 거래 | 매수일 | 매수가 | 매도일 | 매도가 | 수익률 | 사유 |")
                lines.append("|:----:|:------:|-------:|:------:|-------:|-------:|:----:|")

                for trade in r.trades[-10:]:  # 최근 10건
                    exit_date = trade.exit_date.strftime("%Y-%m-%d") if trade.exit_date else "-"
                    exit_price = f"{trade.exit_price:,.0f}" if trade.exit_price else "-"
                    exit_reason_kr = {
                        "death_cross": "데드크로스",
                        "stop_loss": "손절",
                        "take_profit": "익절",
                        "end_of_period": "기간종료",
                    }.get(trade.exit_reason, trade.exit_reason or "-")

                    profit_emoji = (
                        "📈" if trade.profit_rate > 0 else ("📉" if trade.profit_rate < 0 else "➖")
                    )

                    lines.append(
                        f"| {trade.trade_id} | {trade.entry_date.strftime('%Y-%m-%d')} | "
                        f"{trade.entry_price:,.0f} | {exit_date} | {exit_price} | "
                        f"{profit_emoji} {trade.profit_rate:+.2f}% | {exit_reason_kr} |"
                    )

                if len(r.trades) > 10:
                    lines.append(f"| ... | 외 {len(r.trades) - 10}건 | | | | | |")

                lines.append("")

            lines.append("---")
            lines.append("")

    # 오류 종목
    if error_results:
        lines.append("## 3. 오류 종목")
        lines.append("")
        for r in error_results:
            lines.append(f"- **{r.name} ({r.symbol})**: {r.error}")
        lines.append("")

    # 결론
    lines.append("## 4. 결론 및 분석")
    lines.append("")

    if valid_results:
        profitable = [r for r in valid_results if r.total_return > 0]
        unprofitable = [r for r in valid_results if r.total_return <= 0]

        lines.append(f"### 수익성 분석")
        lines.append(
            f"- 수익 종목: {len(profitable)}개 ({len(profitable)/len(valid_results)*100:.1f}%)"
        )
        lines.append(
            f"- 손실 종목: {len(unprofitable)}개 ({len(unprofitable)/len(valid_results)*100:.1f}%)"
        )
        lines.append("")

        if profitable:
            best = max(profitable, key=lambda x: x.total_return)
            lines.append(f"### 최고 성과")
            lines.append(f"- **{best.name} ({best.symbol})**: {best.total_return:+.2f}%")
            lines.append("")

        if unprofitable:
            worst = min(unprofitable, key=lambda x: x.total_return)
            lines.append(f"### 최저 성과")
            lines.append(f"- **{worst.name} ({worst.symbol})**: {worst.total_return:+.2f}%")
            lines.append("")

        lines.append("### 전략 평가")
        lines.append("")

        if avg_return > 10:
            lines.append("✅ **양호**: 평균 수익률 10% 이상")
        elif avg_return > 0:
            lines.append("⚠️ **보통**: 양의 수익률이지만 개선 필요")
        else:
            lines.append("❌ **미흡**: 전략 재검토 필요")

        if avg_mdd < 15:
            lines.append("✅ **양호**: MDD 15% 미만으로 리스크 관리 양호")
        elif avg_mdd < 25:
            lines.append("⚠️ **보통**: MDD 관리 개선 필요")
        else:
            lines.append("❌ **미흡**: MDD가 높아 리스크 관리 필요")

        if avg_win_rate > 50:
            lines.append(f"✅ **양호**: 승률 {avg_win_rate:.1f}%로 50% 초과")
        else:
            lines.append(f"⚠️ **보통**: 승률 {avg_win_rate:.1f}%로 개선 필요")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        "*이 리포트는 자동 생성되었습니다. 투자 결정은 본인의 판단하에 이루어져야 합니다.*"
    )

    report_content = "\n".join(lines)

    # 파일 저장
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_content)

    return report_content


async def main():
    """메인 실행 함수"""
    print("=" * 80)
    print("📊 골든크로스 전략 백테스트 - analysis_history 종목")
    print("=" * 80)

    # 1. 의존성 초기화
    kis_client = KISAPIClient()
    redis_client = await get_redis_client()

    # 2. DB 세션 생성
    db_gen = get_db()
    db_session = await db_gen.__anext__()

    try:
        # 3. analysis_history에서 종목 조회
        print("\n📋 analysis_history 종목 조회...")
        stocks = await get_analysis_history_symbols(db_session)

        if not stocks:
            print("❌ 활성 종목이 없습니다.")
            return

        print(f"✅ {len(stocks)}개 종목 조회됨:")
        for s in stocks:
            print(f"   - {s['name']} ({s['symbol']}) [{s['analysis_type']}]")

        # 4. 서비스 초기화
        market_data_service = MarketDataService(kis_client, redis_client)
        data_loader = BacktestDataLoader(market_data_service, db_session)

        # 5. 백테스트 설정
        strategy_config = GoldenCrossConfig()
        backtest_config = BacktestConfig()
        backtester = GoldenCrossBacktester(strategy_config, backtest_config)

        # 6. 기간 설정 (2년)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=730)  # 약 2년

        print(
            f"\n📅 백테스트 기간: {start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}"
        )
        print("=" * 80)

        # 7. 종목별 백테스트 실행
        results: list[BacktestResult] = []

        for idx, stock in enumerate(stocks, 1):
            symbol = stock["symbol"]
            name = stock["name"] or symbol

            print(f"\n[{idx}/{len(stocks)}] {name} ({symbol}) 백테스트 중...")

            try:
                # 데이터 로드 (DB 캐싱 활용)
                df, actual_start, actual_end = await data_loader.load_ohlcv_data(
                    symbol=symbol,
                    start_date=start_date,
                    end_date=end_date,
                    chunk_days=90,
                    use_cache=True,
                )

                print(
                    f"   📥 데이터: {len(df)}건 ({actual_start.strftime('%Y-%m-%d')} ~ {actual_end.strftime('%Y-%m-%d')})"
                )

                # 백테스트 실행
                result = await backtester.run(
                    symbol=symbol,
                    name=name,
                    df=df,
                    start_date=actual_start,
                    end_date=actual_end,
                )

                if result.error:
                    print(f"   ⚠️ 오류: {result.error}")
                else:
                    emoji = "📈" if result.total_return > 0 else "📉"
                    print(
                        f"   {emoji} 수익률: {result.total_return:+.2f}% | MDD: {result.mdd:.2f}% | 거래: {result.total_trades}회"
                    )

                results.append(result)

            except Exception as e:
                print(f"   ❌ 실패: {e}")
                results.append(
                    BacktestResult(
                        symbol=symbol,
                        name=name,
                        start_date=start_date,
                        end_date=end_date,
                        initial_capital=backtest_config.initial_capital,
                        final_capital=backtest_config.initial_capital,
                        total_return=0.0,
                        annualized_return=0.0,
                        mdd=0.0,
                        mdd_start_date=None,
                        mdd_end_date=None,
                        sharpe_ratio=0.0,
                        win_rate=0.0,
                        total_trades=0,
                        winning_trades=0,
                        losing_trades=0,
                        avg_profit=0.0,
                        avg_loss=0.0,
                        profit_factor=0.0,
                        avg_holding_days=0.0,
                        max_consecutive_wins=0,
                        max_consecutive_losses=0,
                        error=str(e),
                    )
                )

        # 8. 결과 요약 출력
        print("\n" + "=" * 80)
        print("📊 백테스트 결과 요약")
        print("=" * 80)

        valid_results = [r for r in results if r.error is None]

        if valid_results:
            print(f"\n{'종목':<30} {'수익률':>10} {'MDD':>8} {'승률':>8} {'거래수':>8}")
            print("-" * 70)

            for r in sorted(valid_results, key=lambda x: x.total_return, reverse=True):
                emoji = "📈" if r.total_return > 0 else "📉"
                print(
                    f"{emoji} {r.name[:25]:<28} {r.total_return:>+9.2f}% {r.mdd:>7.2f}% {r.win_rate:>7.1f}% {r.total_trades:>8}"
                )

            print("-" * 70)

            avg_return = sum(r.total_return for r in valid_results) / len(valid_results)
            avg_mdd = sum(r.mdd for r in valid_results) / len(valid_results)
            print(f"{'평균':<30} {avg_return:>+9.2f}% {avg_mdd:>7.2f}%")

        # 9. 리포트 생성
        report_path = "reports/golden_cross_backtest_report.md"

        import os

        os.makedirs("reports", exist_ok=True)

        print(f"\n📝 리포트 생성 중...")
        report_content = generate_report(results, report_path)
        print(f"✅ 리포트 저장됨: {report_path}")

        # 10. DB 커밋 및 정리
        await db_session.commit()
        await redis_client.disconnect()

        print("\n" + "=" * 80)
        print("🎉 백테스트 완료!")
        print("=" * 80)

    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        import traceback

        traceback.print_exc()
    finally:
        await db_session.close()


if __name__ == "__main__":
    asyncio.run(main())
