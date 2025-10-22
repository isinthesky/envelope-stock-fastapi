# -*- coding: utf-8 -*-
"""
Backtest Engine - 백테스팅 엔진

일별 시뮬레이션을 수행하는 핵심 백테스팅 로직
"""

from datetime import datetime
from decimal import Decimal

import pandas as pd

from src.application.common.indicators import TechnicalIndicators
from src.application.common.performance_metrics import PerformanceMetrics
from src.application.domain.backtest.dto import (
    BacktestConfigDTO,
    BacktestResultDTO,
    DailyStatsDTO,
    TradeDTO,
)
from src.application.domain.backtest.order_manager import BacktestOrderManager
from src.application.domain.backtest.position_manager import PositionManager
from src.application.domain.strategy.dto import StrategyConfigDTO


class BacktestEngine:
    """백테스팅 엔진"""

    def __init__(
        self,
        symbol: str,
        strategy_config: StrategyConfigDTO,
        backtest_config: BacktestConfigDTO
    ):
        """
        Args:
            symbol: 종목코드
            strategy_config: 전략 설정
            backtest_config: 백테스팅 설정
        """
        self.symbol = symbol
        self.strategy_config = strategy_config
        self.backtest_config = backtest_config

        # 관리자 초기화
        self.order_manager = BacktestOrderManager(backtest_config)
        self.position_manager = PositionManager()

        # 상태 관리
        self.cash = backtest_config.initial_capital
        self.initial_capital = backtest_config.initial_capital

        # 기록
        self.trades: list[TradeDTO] = []
        self.completed_trades: list[dict] = []  # 성과 분석용
        self.daily_stats: list[DailyStatsDTO] = []
        self.equity_curve: list[Decimal] = []

        # 가격 히스토리 (지표 계산용)
        self.price_history: list[float] = []

    async def run(
        self,
        data: pd.DataFrame,
        start_date: datetime,
        end_date: datetime
    ) -> BacktestResultDTO:
        """
        백테스팅 실행

        Args:
            data: OHLCV 데이터
            start_date: 시작일
            end_date: 종료일

        Returns:
            BacktestResultDTO: 백테스팅 결과
        """
        # 초기화
        self._reset()

        # 일별 처리
        for idx, row in data.iterrows():
            current_date = row["timestamp"]
            current_price = Decimal(str(row["close"]))

            # 가격 히스토리 업데이트
            self.price_history.append(row["close"])

            # 일별 처리
            await self._process_day(current_date, current_price, row)

        # 결과 생성
        result = self._generate_result(start_date, end_date)

        return result

    async def _process_day(
        self,
        date: datetime,
        current_price: Decimal,
        row: pd.Series
    ) -> None:
        """
        일별 처리 로직

        Args:
            date: 현재 날짜
            current_price: 현재가
            row: OHLCV 데이터 행
        """
        # 1. 손절/익절 체크 (장 시작 시)
        await self._check_risk_management(date, current_price)

        # 2. 시그널 생성
        signal = self._generate_signal(current_price)

        # 3. 주문 실행
        if signal == "buy" and not self.position_manager.has_position(self.symbol):
            # 매수
            await self._execute_buy(date, current_price)

        elif signal == "sell" and self.position_manager.has_position(self.symbol):
            # 매도
            await self._execute_sell(date, current_price, exit_reason="signal")

        # 4. 포지션 평가액 업데이트
        position_value = self.position_manager.update_positions({
            self.symbol: current_price
        })

        # 5. 일별 통계 기록
        self._update_daily_stats(date, position_value)

    def _reset(self) -> None:
        """상태 초기화"""
        self.cash = self.backtest_config.initial_capital
        self.trades.clear()
        self.completed_trades.clear()
        self.daily_stats.clear()
        self.equity_curve.clear()
        self.price_history.clear()
        self.position_manager.clear_all_positions()

    def _generate_signal(self, current_price: Decimal) -> str:
        """
        매매 시그널 생성

        Args:
            current_price: 현재가

        Returns:
            str: "buy" (매수), "sell" (매도), "hold" (보유)
        """
        # 최소 기간 데이터 확인
        bb_period = self.strategy_config.bollinger_band.period
        env_period = self.strategy_config.envelope.period
        min_period = max(bb_period, env_period)

        if len(self.price_history) < min_period:
            return "hold"

        # 볼린저 밴드 계산
        bb_bands = TechnicalIndicators.calculate_bollinger_bands(
            self.price_history,
            period=bb_period,
            std_multiplier=self.strategy_config.bollinger_band.std_multiplier
        )

        # 엔벨로프 계산
        env_bands = TechnicalIndicators.calculate_envelope(
            self.price_history,
            period=env_period,
            percentage=self.strategy_config.envelope.percentage
        )

        # 결합 시그널 생성
        signal = TechnicalIndicators.generate_combined_signal(
            current_price=float(current_price),
            bb_bands=bb_bands,
            envelope_bands=env_bands,
            use_strict_mode=True  # 엄격 모드 사용
        )

        return signal

    async def _execute_buy(self, date: datetime, price: Decimal) -> None:
        """
        매수 실행

        Args:
            date: 거래일
            price: 매수 가격
        """
        # 포지션 크기 계산
        quantity = self.order_manager.calculate_position_size(
            available_cash=self.cash,
            allocation_ratio=self.strategy_config.position.allocation_ratio,
            current_price=price
        )

        if quantity == 0:
            return

        # 매수 가능 여부 확인
        if not self.order_manager.can_afford(self.cash, price, quantity):
            return

        # 주문 실행
        trade, total_cost = self.order_manager.execute_buy_order(
            symbol=self.symbol,
            price=price,
            quantity=quantity,
            date=date
        )

        # 현금 차감
        self.cash -= total_cost

        # 포지션 오픈
        self.position_manager.open_position(
            symbol=self.symbol,
            quantity=quantity,
            entry_price=trade.entry_price,
            entry_date=date,
            trade_id=trade.trade_id
        )

        # 거래 기록
        self.trades.append(trade)

    async def _execute_sell(
        self,
        date: datetime,
        price: Decimal,
        exit_reason: str = "signal"
    ) -> None:
        """
        매도 실행

        Args:
            date: 거래일
            price: 매도 가격
            exit_reason: 청산 이유
        """
        position = self.position_manager.get_position(self.symbol)
        if not position:
            return

        # 기존 매수 거래 찾기
        buy_trade = next(
            (t for t in self.trades if t.trade_id == position.trade_id),
            None
        )
        if not buy_trade:
            return

        # 주문 실행
        completed_trade, net_proceeds = self.order_manager.execute_sell_order(
            trade=buy_trade,
            price=price,
            date=date,
            exit_reason=exit_reason
        )

        # 현금 증가
        self.cash += net_proceeds

        # 포지션 청산
        self.position_manager.close_position(self.symbol)

        # 거래 기록 업데이트
        for idx, trade in enumerate(self.trades):
            if trade.trade_id == completed_trade.trade_id:
                self.trades[idx] = completed_trade
                break

        # 완료된 거래 추가 (성과 분석용)
        self.completed_trades.append({
            "profit_rate": completed_trade.profit_rate,
            "holding_days": completed_trade.holding_days
        })

    async def _check_risk_management(self, date: datetime, current_price: Decimal) -> None:
        """
        리스크 관리 체크 (손절/익절/트레일링스톱)

        Args:
            date: 현재 날짜
            current_price: 현재가
        """
        if not self.position_manager.has_position(self.symbol):
            return

        risk_config = self.strategy_config.risk_management

        # 손절 체크
        if risk_config.use_stop_loss and risk_config.stop_loss_ratio is not None:
            if self.position_manager.check_stop_loss(
                self.symbol, current_price, risk_config.stop_loss_ratio
            ):
                await self._execute_sell(date, current_price, exit_reason="stop_loss")
                return

        # 익절 체크
        if risk_config.use_take_profit and risk_config.take_profit_ratio is not None:
            if self.position_manager.check_take_profit(
                self.symbol, current_price, risk_config.take_profit_ratio
            ):
                await self._execute_sell(date, current_price, exit_reason="take_profit")
                return

        # Trailing Stop 체크
        if risk_config.use_trailing_stop and risk_config.trailing_stop_ratio is not None:
            if self.position_manager.check_trailing_stop(
                self.symbol, current_price, risk_config.trailing_stop_ratio
            ):
                await self._execute_sell(date, current_price, exit_reason="trailing_stop")
                return

    def _update_daily_stats(self, date: datetime, position_value: Decimal) -> None:
        """
        일별 통계 업데이트

        Args:
            date: 날짜
            position_value: 포지션 평가액
        """
        # 총 자산
        equity = self.cash + position_value
        self.equity_curve.append(equity)

        # 수익률 계산
        daily_return = 0.0
        if len(self.equity_curve) > 1:
            prev_equity = self.equity_curve[-2]
            daily_return = float((equity - prev_equity) / prev_equity * 100) if prev_equity > 0 else 0.0

        cumulative_return = float((equity - self.initial_capital) / self.initial_capital * 100)

        # 낙폭 계산
        if len(self.equity_curve) > 0:
            equity_array = [float(e) for e in self.equity_curve]
            cummax = max(equity_array)
            drawdown = float((equity - Decimal(str(cummax))) / Decimal(str(cummax)) * 100) if cummax > 0 else 0.0
        else:
            drawdown = 0.0

        # 일별 통계 기록
        stats = DailyStatsDTO(
            date=date,
            equity=equity,
            cash=self.cash,
            position_value=position_value,
            daily_return=daily_return,
            cumulative_return=cumulative_return,
            drawdown=drawdown
        )

        self.daily_stats.append(stats)

    def _generate_result(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> BacktestResultDTO:
        """
        백테스팅 결과 생성

        Args:
            start_date: 시작일
            end_date: 종료일

        Returns:
            BacktestResultDTO: 백테스팅 결과
        """
        final_capital = self.equity_curve[-1] if self.equity_curve else self.initial_capital

        # 수익 지표
        total_return = PerformanceMetrics.calculate_total_return(
            self.initial_capital, final_capital
        )
        annualized_return = PerformanceMetrics.calculate_annualized_return(
            self.initial_capital, final_capital, start_date, end_date
        )
        years = (end_date - start_date).days / 365
        cagr = PerformanceMetrics.calculate_cagr(
            self.initial_capital, final_capital, years
        )

        # 리스크 지표
        mdd_info = PerformanceMetrics.calculate_mdd(self.equity_curve)

        # DataFrame 생성 (변동성 계산용)
        equity_df = pd.DataFrame({
            "timestamp": [s.date for s in self.daily_stats],
            "equity": [float(s.equity) for s in self.daily_stats]
        })

        volatility = PerformanceMetrics.calculate_volatility(equity_df)
        sharpe = PerformanceMetrics.calculate_sharpe_ratio(annualized_return, volatility)
        sortino = PerformanceMetrics.calculate_sortino_ratio(equity_df, annualized_return)
        calmar = PerformanceMetrics.calculate_calmar_ratio(annualized_return, mdd_info["mdd"])
        var_95 = PerformanceMetrics.calculate_var(equity_df)

        # 거래 통계
        trade_stats = PerformanceMetrics.calculate_trade_count(self.completed_trades)
        win_rate = PerformanceMetrics.calculate_win_rate(self.completed_trades)
        profit_factor = PerformanceMetrics.calculate_profit_factor(self.completed_trades)
        avg_stats = PerformanceMetrics.calculate_avg_profit_loss(self.completed_trades)
        holding_stats = PerformanceMetrics.calculate_avg_holding_period(self.completed_trades)
        streak_stats = PerformanceMetrics.calculate_consecutive_wins_losses(self.completed_trades)

        return BacktestResultDTO(
            # 기본 정보
            symbol=self.symbol,
            start_date=start_date,
            end_date=end_date,
            initial_capital=self.initial_capital,
            final_capital=final_capital,
            # 수익 지표
            total_return=total_return,
            annualized_return=annualized_return,
            cagr=cagr,
            # 리스크 지표
            mdd=mdd_info["mdd"],
            volatility=volatility,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            calmar_ratio=calmar,
            var_95=var_95,
            # 거래 통계
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
            # 상세 데이터
            trades=self.trades,
            daily_stats=self.daily_stats
        )
