# -*- coding: utf-8 -*-
"""
News Trading Backtest Engine - 뉴스 기반 단타 백테스트 엔진

분봉 데이터 기반 백테스팅:
- 09:10 진입 시뮬레이션
- 분할 익절 + 손절 + 시간 청산
- 거래 비용/슬리피지 반영
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, time, date, timedelta
from decimal import Decimal
from typing import Any

import pandas as pd

from src.application.domain.news_trading.dto import (
    ExitReason,
    TradingStatus,
    TradingResultDTO,
    NewsTradingStrategyConfigDTO,
    NewsTradingBacktestRequestDTO,
    NewsTradingBacktestResultDTO,
    NewsEventType,
)
from src.application.domain.news_trading.exit_manager import BacktestExitManager
from src.application.domain.news_trading.momentum_detector import SimpleMovingMomentum


logger = logging.getLogger(__name__)


@dataclass
class BacktestPosition:
    """백테스트 포지션"""
    symbol: str
    entry_date: date
    entry_time: time
    entry_price: float
    total_quantity: int
    remaining_quantity: int

    first_exit_done: bool = False
    first_exit_price: float | None = None
    first_exit_quantity: int | None = None
    first_exit_reason: ExitReason | None = None

    realized_pnl: float = 0.0
    status: TradingStatus = TradingStatus.POSITION_OPEN


@dataclass
class DaySimulation:
    """일별 시뮬레이션 결과"""
    date: date
    is_trading_day: bool = True
    is_no_trade_day: bool = False
    no_trade_reason: str | None = None

    entry_symbol: str | None = None
    entry_price: float | None = None
    entry_quantity: int | None = None

    exit_price: float | None = None
    exit_reason: ExitReason | None = None
    realized_pnl: float = 0.0
    profit_rate: float = 0.0

    # 분할 익절 추적
    first_exit_price: float | None = None
    first_exit_quantity: int | None = None
    first_exit_reason: ExitReason | None = None


class NewsTradingBacktestEngine:
    """
    뉴스 기반 단타 백테스트 엔진

    주요 기능:
    1. 분봉 데이터 기반 일별 시뮬레이션
    2. 복합 조건 필터링 시뮬레이션
    3. 분할 익절 + 손절 + 시간 청산
    4. 성과 지표 계산
    """

    def __init__(
        self,
        config: NewsTradingStrategyConfigDTO | None = None,
    ):
        """
        Args:
            config: 전략 설정
        """
        self.config = config or NewsTradingStrategyConfigDTO()
        self.exit_manager = BacktestExitManager(
            config=self.config.trading_session.exit_config
        )

        # 비용 설정
        self.commission_rate = self.config.backtest_commission_rate
        self.tax_rate = self.config.backtest_tax_rate
        self.slippage_rate = self.config.backtest_slippage_rate

    def run_backtest(
        self,
        request: NewsTradingBacktestRequestDTO,
        daily_data: dict[str, pd.DataFrame],
        minute_data: dict[str, pd.DataFrame] | None = None,
    ) -> NewsTradingBacktestResultDTO:
        """
        백테스트 실행

        Args:
            request: 백테스트 요청
            daily_data: 종목별 일봉 데이터 {symbol: DataFrame}
            minute_data: 종목별 분봉 데이터 {symbol: DataFrame} (선택)

        Returns:
            백테스트 결과
        """
        self.config = request.strategy_config

        initial_capital = float(request.initial_capital)
        current_capital = initial_capital
        cash = initial_capital

        # 결과 저장
        trades: list[TradingResultDTO] = []
        equity_curve: list[float] = [initial_capital]
        daily_returns: list[float] = []
        day_simulations: list[DaySimulation] = []

        # 거래일 추출
        trading_days = self._get_trading_days(
            request.start_date, request.end_date, daily_data
        )

        no_trade_days = 0
        active_trading_days = 0

        for trading_date in trading_days:
            day_sim = self._simulate_day(
                trading_date=trading_date,
                symbols=request.symbols,
                daily_data=daily_data,
                minute_data=minute_data,
                available_capital=cash,
            )

            day_simulations.append(day_sim)

            if day_sim.is_no_trade_day:
                no_trade_days += 1
                continue

            if day_sim.entry_symbol is None:
                continue

            active_trading_days += 1

            # 손익 반영
            cash += day_sim.realized_pnl
            current_capital = cash
            equity_curve.append(current_capital)

            if len(equity_curve) > 1:
                daily_return = (equity_curve[-1] - equity_curve[-2]) / equity_curve[-2]
                daily_returns.append(daily_return)

            # 거래 결과 기록
            if day_sim.entry_symbol and day_sim.entry_price:
                trade = TradingResultDTO(
                    trade_id=f"{day_sim.entry_symbol}_{trading_date.strftime('%Y%m%d')}",
                    symbol=day_sim.entry_symbol,
                    name=day_sim.entry_symbol,
                    entry_time=datetime.combine(trading_date, time(9, 10)),
                    entry_price=Decimal(str(day_sim.entry_price)),
                    entry_quantity=day_sim.entry_quantity or 0,
                    first_exit_time=None,
                    first_exit_price=Decimal(str(day_sim.first_exit_price)) if day_sim.first_exit_price else None,
                    first_exit_quantity=day_sim.first_exit_quantity,
                    first_exit_reason=day_sim.first_exit_reason,
                    final_exit_time=datetime.combine(trading_date, time(10, 40)),
                    final_exit_price=Decimal(str(day_sim.exit_price)) if day_sim.exit_price else None,
                    final_exit_quantity=day_sim.entry_quantity,
                    final_exit_reason=day_sim.exit_reason,
                    realized_profit=Decimal(str(day_sim.realized_pnl)),
                    realized_profit_rate=day_sim.profit_rate,
                    status=TradingStatus.CLOSED,
                    holding_minutes=90,  # 09:10 ~ 10:40
                    news_score=0.0,
                    event_types=[],
                    momentum_signals_detected=[],
                )
                trades.append(trade)

        # 성과 지표 계산
        result = self._calculate_metrics(
            initial_capital=initial_capital,
            final_capital=current_capital,
            trades=trades,
            equity_curve=equity_curve,
            daily_returns=daily_returns,
            total_trading_days=len(trading_days),
            no_trade_days=no_trade_days,
            active_trading_days=active_trading_days,
            request=request,
        )

        return result

    def _simulate_day(
        self,
        trading_date: date,
        symbols: list[str],
        daily_data: dict[str, pd.DataFrame],
        minute_data: dict[str, pd.DataFrame] | None,
        available_capital: float,
    ) -> DaySimulation:
        """
        일별 시뮬레이션

        Args:
            trading_date: 거래일
            symbols: 대상 종목
            daily_data: 일봉 데이터
            minute_data: 분봉 데이터
            available_capital: 가용 자본

        Returns:
            일별 시뮬레이션 결과
        """
        day_sim = DaySimulation(date=trading_date)

        # 종목 선정 (단순화: 첫 번째 유효 종목)
        selected_symbol = None
        entry_price = 0.0

        for symbol in symbols:
            if symbol not in daily_data:
                continue

            df = daily_data[symbol]
            day_row = df[df.index.date == trading_date] if hasattr(df.index, 'date') else df[df["date"] == trading_date]

            if day_row.empty:
                continue

            row = day_row.iloc[0]

            # 간단한 필터: 전일 대비 갭 상승
            open_price = float(row.get("open", row.get("시가", 0)))
            prev_close = float(row.get("prev_close", row.get("전일종가", open_price)))

            if prev_close > 0:
                gap_rate = (open_price - prev_close) / prev_close
                # 갭 상승 1% 이상인 종목 선정
                if gap_rate >= 0.01:
                    selected_symbol = symbol
                    entry_price = open_price * (1 + self.slippage_rate)  # 슬리피지 반영
                    break

        if selected_symbol is None:
            day_sim.is_no_trade_day = True
            day_sim.no_trade_reason = "조건 충족 종목 없음"
            return day_sim

        # 포지션 사이즈 계산
        position_ratio = self.config.safety_guard.position_sizing.max_position_ratio
        position_amount = available_capital * position_ratio
        quantity = int(position_amount / entry_price) if entry_price > 0 else 0

        if quantity <= 0:
            day_sim.is_no_trade_day = True
            day_sim.no_trade_reason = "자본 부족"
            return day_sim

        day_sim.entry_symbol = selected_symbol
        day_sim.entry_price = entry_price
        day_sim.entry_quantity = quantity

        # 청산 시뮬레이션
        self._simulate_exit(day_sim, daily_data, minute_data, trading_date)

        return day_sim

    def _simulate_exit(
        self,
        day_sim: DaySimulation,
        daily_data: dict[str, pd.DataFrame],
        minute_data: dict[str, pd.DataFrame] | None,
        trading_date: date,
    ) -> None:
        """
        청산 시뮬레이션

        분봉 데이터가 있으면 분봉 기반, 없으면 일봉 기반
        """
        symbol = day_sim.entry_symbol
        if not symbol or not day_sim.entry_price:
            return

        entry_price = day_sim.entry_price
        quantity = day_sim.entry_quantity or 0
        remaining_quantity = quantity
        first_exit_done = False
        total_realized = 0.0

        staged_config = self.config.trading_session.exit_config.staged_profit_taking
        exit_config = self.config.trading_session.exit_config

        # 분봉 데이터 사용
        if minute_data and symbol in minute_data:
            df = minute_data[symbol]

            # 거래 시간 필터 (09:10 ~ 10:40)
            if hasattr(df.index, 'time'):
                mask = (df.index.date == trading_date) & \
                       (df.index.time >= time(9, 10)) & \
                       (df.index.time <= time(10, 40))
            else:
                mask = df["date"].dt.date == trading_date

            day_bars = df[mask] if not df.empty else df

            for idx, bar in day_bars.iterrows():
                bar_time = idx.time() if hasattr(idx, 'time') else time(10, 40)
                bar_dict = {
                    "high": float(bar.get("high", bar.get("고가", entry_price))),
                    "low": float(bar.get("low", bar.get("저가", entry_price))),
                    "close": float(bar.get("close", bar.get("종가", entry_price))),
                }

                exit_reason, exit_price = self.exit_manager.check_exit_from_bar(
                    entry_price=entry_price,
                    current_bar=bar_dict,
                    first_exit_done=first_exit_done,
                    bar_time=datetime.combine(trading_date, bar_time),
                )

                if exit_reason:
                    if exit_reason == ExitReason.FIRST_PROFIT_TAKING and not first_exit_done:
                        # 1차 익절
                        exit_qty = int(quantity * staged_config.first_take_profit_ratio)
                        profit_info = self.exit_manager.calculate_profit(
                            entry_price, exit_price, exit_qty,
                            self.commission_rate, self.tax_rate
                        )
                        total_realized += profit_info["net_profit"]
                        remaining_quantity -= exit_qty
                        first_exit_done = True

                        day_sim.first_exit_price = exit_price
                        day_sim.first_exit_quantity = exit_qty
                        day_sim.first_exit_reason = exit_reason

                    elif exit_reason in [
                        ExitReason.STOP_LOSS,
                        ExitReason.TIME_EXIT,
                        ExitReason.SECOND_PROFIT_TAKING,
                    ]:
                        # 전량 청산
                        profit_info = self.exit_manager.calculate_profit(
                            entry_price, exit_price, remaining_quantity,
                            self.commission_rate, self.tax_rate
                        )
                        total_realized += profit_info["net_profit"]
                        remaining_quantity = 0

                        day_sim.exit_price = exit_price
                        day_sim.exit_reason = exit_reason
                        day_sim.realized_pnl = total_realized
                        day_sim.profit_rate = (total_realized / (entry_price * quantity)) * 100
                        return

        # 일봉 데이터만 있는 경우
        else:
            if symbol in daily_data:
                df = daily_data[symbol]
                day_row = df[df.index.date == trading_date] if hasattr(df.index, 'date') else df[df["date"] == trading_date]

                if not day_row.empty:
                    row = day_row.iloc[0]
                    bar_dict = {
                        "high": float(row.get("high", row.get("고가", entry_price))),
                        "low": float(row.get("low", row.get("저가", entry_price))),
                        "close": float(row.get("close", row.get("종가", entry_price))),
                    }

                    exit_reason, exit_price = self.exit_manager.check_exit_from_bar(
                        entry_price=entry_price,
                        current_bar=bar_dict,
                        first_exit_done=False,
                    )

                    if exit_reason:
                        profit_info = self.exit_manager.calculate_profit(
                            entry_price, exit_price if exit_price > 0 else bar_dict["close"],
                            quantity, self.commission_rate, self.tax_rate
                        )
                        day_sim.exit_price = exit_price if exit_price > 0 else bar_dict["close"]
                        day_sim.exit_reason = exit_reason
                        day_sim.realized_pnl = profit_info["net_profit"]
                        day_sim.profit_rate = profit_info["profit_rate"]
                        return

        # 시간 청산 (기본)
        if remaining_quantity > 0:
            close_price = entry_price  # 기본값 (데이터 없을 경우)

            if symbol in daily_data:
                df = daily_data[symbol]
                day_row = df[df.index.date == trading_date] if hasattr(df.index, 'date') else df[df["date"] == trading_date]
                if not day_row.empty:
                    close_price = float(day_row.iloc[0].get("close", day_row.iloc[0].get("종가", entry_price)))

            profit_info = self.exit_manager.calculate_profit(
                entry_price, close_price, remaining_quantity,
                self.commission_rate, self.tax_rate
            )
            total_realized += profit_info["net_profit"]

            day_sim.exit_price = close_price
            day_sim.exit_reason = ExitReason.TIME_EXIT
            day_sim.realized_pnl = total_realized
            day_sim.profit_rate = (total_realized / (entry_price * quantity)) * 100

    def _get_trading_days(
        self,
        start_date: datetime,
        end_date: datetime,
        daily_data: dict[str, pd.DataFrame],
    ) -> list[date]:
        """거래일 목록 추출"""
        trading_days: set[date] = set()

        for symbol, df in daily_data.items():
            if hasattr(df.index, 'date'):
                dates = df.index.date
            elif "date" in df.columns:
                dates = pd.to_datetime(df["date"]).dt.date
            else:
                continue

            for d in dates:
                if start_date.date() <= d <= end_date.date():
                    trading_days.add(d)

        return sorted(list(trading_days))

    def _calculate_metrics(
        self,
        initial_capital: float,
        final_capital: float,
        trades: list[TradingResultDTO],
        equity_curve: list[float],
        daily_returns: list[float],
        total_trading_days: int,
        no_trade_days: int,
        active_trading_days: int,
        request: NewsTradingBacktestRequestDTO,
    ) -> NewsTradingBacktestResultDTO:
        """성과 지표 계산"""
        # 총 수익률
        total_return = ((final_capital - initial_capital) / initial_capital) * 100

        # 연환산 수익률
        years = (request.end_date - request.start_date).days / 365
        annualized_return = ((final_capital / initial_capital) ** (1 / years) - 1) * 100 if years > 0 else 0

        # MDD
        mdd = self._calculate_mdd(equity_curve)

        # Sharpe Ratio
        sharpe_ratio = self._calculate_sharpe(daily_returns)

        # 거래 통계
        total_trades = len(trades)
        winning_trades = sum(1 for t in trades if t.realized_profit > 0)
        losing_trades = sum(1 for t in trades if t.realized_profit < 0)
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0

        # 평균 수익/손실
        winning_pnls = [float(t.realized_profit) for t in trades if t.realized_profit > 0]
        losing_pnls = [float(t.realized_profit) for t in trades if t.realized_profit < 0]

        avg_win = (sum(winning_pnls) / len(winning_pnls)) if winning_pnls else 0
        avg_loss = (sum(losing_pnls) / len(losing_pnls)) if losing_pnls else 0

        # Profit Factor
        gross_profit = sum(winning_pnls)
        gross_loss = abs(sum(losing_pnls))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 0

        # 청산 사유별 통계
        exit_reason_stats: dict[str, int] = {}
        for trade in trades:
            if trade.final_exit_reason:
                reason = trade.final_exit_reason.value
                exit_reason_stats[reason] = exit_reason_stats.get(reason, 0) + 1

        return NewsTradingBacktestResultDTO(
            start_date=request.start_date,
            end_date=request.end_date,
            initial_capital=request.initial_capital,
            final_capital=Decimal(str(final_capital)),
            strategy_config=self.config,
            total_return=total_return,
            annualized_return=annualized_return,
            mdd=mdd,
            sharpe_ratio=sharpe_ratio,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
            avg_win=avg_win / initial_capital * 100 if initial_capital > 0 else 0,
            avg_loss=avg_loss / initial_capital * 100 if initial_capital > 0 else 0,
            profit_factor=profit_factor,
            exit_reason_stats=exit_reason_stats,
            event_type_performance={},
            trades=trades,
            total_trading_days=total_trading_days,
            no_trade_days=no_trade_days,
            active_trading_days=active_trading_days,
        )

    @staticmethod
    def _calculate_mdd(equity_curve: list[float]) -> float:
        """최대 낙폭 계산"""
        if not equity_curve:
            return 0.0

        peak = equity_curve[0]
        max_drawdown = 0.0

        for value in equity_curve:
            if value > peak:
                peak = value
            drawdown = (peak - value) / peak
            if drawdown > max_drawdown:
                max_drawdown = drawdown

        return max_drawdown * 100

    @staticmethod
    def _calculate_sharpe(returns: list[float], risk_free_rate: float = 0.02) -> float:
        """Sharpe Ratio 계산 (연환산)"""
        if not returns or len(returns) < 2:
            return 0.0

        import statistics

        avg_return = statistics.mean(returns)
        std_return = statistics.stdev(returns)

        if std_return == 0:
            return 0.0

        # 일간 수익률 → 연환산
        daily_rf = risk_free_rate / 252
        excess_return = avg_return - daily_rf
        sharpe = (excess_return / std_return) * (252 ** 0.5)

        return sharpe
