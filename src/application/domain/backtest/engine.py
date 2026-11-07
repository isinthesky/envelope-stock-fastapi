# -*- coding: utf-8 -*-
"""
Backtest Engine - 백테스팅 엔진

일별 시뮬레이션을 수행하는 핵심 백테스팅 로직
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal, assert_never

import pandas as pd

from src.application.domain.backtest.dto import (
    BacktestConfigDTO,
    BacktestResultDTO,
    DailyStatsDTO,
    TradeDTO,
)
from src.application.domain.backtest.generators import (
    BaseSignalGenerator,
    create_signal_generator,
)
from src.application.domain.backtest.order_manager import BacktestOrderManager
from src.application.domain.backtest.position_manager import Position, PositionManager
from src.application.domain.backtest.result_builder import build_backtest_result
from src.application.domain.strategy.dto import StrategyConfigDTO
from src.application.domain.strategy.strategy_contract import GoldenCrossRiskExitReason

PendingSignal = Literal["buy", "sell"]


class BacktestEngine:
    """백테스팅 엔진"""

    def __init__(
        self,
        symbol: str,
        strategy_config: StrategyConfigDTO,
        backtest_config: BacktestConfigDTO,
        strategy_type: str = "golden_cross",
        strategy_params: dict | None = None,
    ):
        self.symbol = symbol
        self.strategy_config = strategy_config
        self.backtest_config = backtest_config
        self.strategy_type = strategy_type
        self.strategy_params = strategy_params or {}

        params = self.strategy_params
        if strategy_type == "golden_cross":
            self.signal_generator: BaseSignalGenerator = create_signal_generator(
                strategy_type="golden_cross",
                short_period=params.get("short_period", 55),
                long_period=params.get("long_period", 165),
                stoch_k_period=params.get("stoch_k_period", 14),
                stoch_d_period=params.get("stoch_d_period", 3),
                stoch_oversold=params.get("stoch_oversold", 30.0),
                stoch_overbought=params.get("stoch_overbought", 70.0),
                require_k_above_d_for_buy=params.get("require_k_above_d_for_buy", False),
                require_k_below_d_for_sell=params.get("require_k_below_d_for_sell", False),
                buy_recovery_threshold=params.get(
                    "buy_recovery_threshold", params.get("stoch_oversold", 30.0) + 5.0
                ),
                min_pullback_bars=params.get("min_pullback_bars", 2),
                min_reentry_cooldown_bars=params.get("min_reentry_cooldown_bars", 5),
                disable_stoch_overbought_sell=params.get("disable_stoch_overbought_sell", True),
                # 리스크 청산 후 새 골든크로스 요구(라이브 FSM WAITING_FOR_GC 정합, 기본 True)
                require_fresh_cross_after_exit=params.get("require_fresh_cross_after_exit", True),
            )
        else:
            # golden_cross 외 타입은 지원하지 않는다. 미지원 타입은 명시적으로 실패한다.
            self.signal_generator = create_signal_generator(strategy_type=strategy_type, **params)

        self.order_manager = BacktestOrderManager(backtest_config)
        self.position_manager = PositionManager()
        self.cash = backtest_config.initial_capital
        self.initial_capital = backtest_config.initial_capital
        self.trades: list[TradeDTO] = []
        self.completed_trades: list[dict] = []
        self.daily_stats: list[DailyStatsDTO] = []
        self.equity_curve: list[Decimal] = []
        self.price_history: list[float] = []
        self.high_history: list[float] = []
        self.low_history: list[float] = []
        self.close_history: list[float] = []
        self.last_exit_date: datetime | None = None
        self.pending_signal: PendingSignal | None = None
        # 부분익절 진행 단계(포지션 단위, 0=미실행/1=1차 완료/2=2차 완료).
        # lot 단위 플래그는 같은 진입가의 모든 lot을 같은 날 +10%에 전량 청산시키는
        # 버그가 있었다 → 포지션(심볼) 단위로 1개 tranche만 청산하도록 추적한다.
        self.partial_tp_stage: dict[str, int] = {}
        self.last_bar_date: datetime | None = None
        self.last_bar_price: Decimal | None = None

    async def run(
        self, data: pd.DataFrame, start_date: datetime, end_date: datetime
    ) -> BacktestResultDTO:
        self._reset()
        for _, row in data.iterrows():
            current_date = row["timestamp"]
            current_price = Decimal(str(row["close"]))
            self.price_history.append(row["close"])
            self.high_history.append(float(row.get("high", row["close"])))
            self.low_history.append(float(row.get("low", row["close"])))
            self.close_history.append(float(row["close"]))
            await self._process_day(current_date, current_price, row)
            self.last_bar_date = current_date
            self.last_bar_price = current_price
        self._apply_final_liquidation_mark()
        return self._generate_result(start_date, end_date)

    async def _process_day(self, date: datetime, current_price: Decimal, row: pd.Series) -> None:
        open_price = Decimal(str(row.get("open", row["close"])))
        execution_timing = self.backtest_config.execution_timing

        match execution_timing:
            case "next_open":
                await self._execute_pending_signal(date, open_price)
            case "next_close" | "same_close":
                pass
            case unreachable:
                assert_never(unreachable)

        await self._check_risk_management(date, current_price)

        match execution_timing:
            case "next_close":
                await self._execute_pending_signal(date, current_price)
            case "next_open" | "same_close":
                pass
            case unreachable:
                assert_never(unreachable)

        signal = self._generate_signal(current_price)

        match execution_timing:
            case "same_close":
                await self._execute_signal(date, current_price, signal)
            case "next_open" | "next_close":
                self._queue_signal(signal)
            case unreachable:
                assert_never(unreachable)

        position_value = self.position_manager.update_positions({self.symbol: current_price})
        self._update_daily_stats(date, position_value)

    async def _execute_pending_signal(self, date: datetime, price: Decimal) -> None:
        signal = self.pending_signal
        self.pending_signal = None
        if signal is None:
            return
        await self._execute_signal(date, price, signal)

    async def _execute_signal(self, date: datetime, price: Decimal, signal: str) -> None:
        if signal == "buy" and not self.position_manager.has_position(self.symbol):
            await self._execute_buy(date, price)
        elif signal == "sell" and self.position_manager.has_position(self.symbol):
            await self._execute_sell_all(date, price, exit_reason="signal")

    def _queue_signal(self, signal: str) -> None:
        if signal == "buy" and not self.position_manager.has_position(self.symbol):
            self.pending_signal = "buy"
        elif signal == "sell" and self.position_manager.has_position(self.symbol):
            self.pending_signal = "sell"

    def _reset(self) -> None:
        self.cash = self.backtest_config.initial_capital
        self.trades.clear()
        self.completed_trades.clear()
        self.daily_stats.clear()
        self.equity_curve.clear()
        self.price_history.clear()
        self.high_history.clear()
        self.low_history.clear()
        self.close_history.clear()
        self.position_manager.clear_all_positions()
        self.last_exit_date = None
        self.pending_signal = None
        self.partial_tp_stage.clear()
        self.last_bar_date = None
        self.last_bar_price = None
        if hasattr(self.signal_generator, "reset"):
            self.signal_generator.reset()

    def _calculate_current_atr(self) -> float | None:
        from src.application.common.indicators import TechnicalIndicators

        atr_period = self.strategy_config.risk_management.atr_period
        return TechnicalIndicators.calculate_atr(
            self.high_history, self.low_history, self.close_history, period=atr_period
        )

    def _generate_signal(self, current_price: Decimal) -> str:
        if self.strategy_type == "golden_cross":
            return self.signal_generator.generate_signal(
                price_history=self.price_history,
                current_price=current_price,
                high_history=self.high_history,
                low_history=self.low_history,
                close_history=self.close_history,
            )
        return self.signal_generator.generate_signal(
            price_history=self.price_history, current_price=current_price
        )

    async def _execute_buy(self, date: datetime, price: Decimal) -> None:
        quantity = self.order_manager.calculate_position_size(
            self.cash, self.strategy_config.position.allocation_ratio, price
        )
        if quantity == 0 or not self.order_manager.can_afford(self.cash, price, quantity):
            return

        lot_plan = self._build_entry_lot_plan(quantity)
        self.partial_tp_stage[self.symbol] = 0
        risk_config = self.strategy_config.risk_management
        entry_atr = (
            self._calculate_current_atr()
            if (risk_config.use_atr_stop_loss or risk_config.use_atr_trailing_stop)
            else None
        )

        for lot_quantity in lot_plan:
            trade, total_cost = self.order_manager.execute_buy_order(
                symbol=self.symbol, price=price, quantity=lot_quantity, date=date
            )
            if self.cash < total_cost:
                continue
            self.cash -= total_cost
            self.position_manager.open_position(
                self.symbol,
                lot_quantity,
                trade.entry_price,
                date,
                trade.trade_id,
                entry_atr=entry_atr,
            )
            self.trades.append(trade)

    def _build_entry_lot_plan(self, quantity: int) -> list[int]:
        if quantity <= 0:
            return []
        ratios = self.strategy_params.get("entry_lot_ratios", [0.5, 0.3, 0.2])
        lots: list[int] = []
        allocated = 0
        for idx, ratio in enumerate(ratios):
            if idx == len(ratios) - 1:
                lot_qty = quantity - allocated
            else:
                lot_qty = int(quantity * ratio)
                allocated += lot_qty
            if lot_qty > 0:
                lots.append(lot_qty)
        if not lots:
            lots.append(quantity)
        return lots

    async def _execute_sell_all(
        self, date: datetime, price: Decimal, exit_reason: str = "signal"
    ) -> None:
        for position in list(self.position_manager.get_positions(self.symbol)):
            await self._close_position_lot(position, date, price, exit_reason)

    async def _close_position_lot(
        self, position: Position, date: datetime, price: Decimal, exit_reason: str
    ) -> None:
        buy_trade = next((t for t in self.trades if t.trade_id == position.trade_id), None)
        if not buy_trade:
            return
        completed_trade, net_proceeds = self.order_manager.execute_sell_order(
            trade=buy_trade, price=price, date=date, exit_reason=exit_reason
        )
        self.cash += net_proceeds
        self.position_manager.close_lot(self.symbol, position.trade_id)
        for idx, trade in enumerate(self.trades):
            if trade.trade_id == completed_trade.trade_id:
                self.trades[idx] = completed_trade
                break
        self.completed_trades.append(
            {
                "profit_rate": completed_trade.profit_rate,
                "holding_days": completed_trade.holding_days,
                # 금액 기준 Profit Factor용(KRW, 비용 차감 후)
                "profit": completed_trade.profit,
            }
        )
        self.last_exit_date = date
        if not self.position_manager.has_position(self.symbol):
            self.partial_tp_stage.pop(self.symbol, None)
            # 리스크 청산(손절/트레일링 등) 후 재진입 재무장: 라이브 FSM은 모든 청산 후
            # WAITING_FOR_GC로 리셋되어 새 골든크로스가 필요하다.
            notify = getattr(self.signal_generator, "notify_exit", None)
            if notify is not None and exit_reason != "signal":
                notify()

    async def _check_risk_management(self, date: datetime, current_price: Decimal) -> None:
        if not self.position_manager.has_position(self.symbol):
            return
        risk_config = self.strategy_config.risk_management
        partial_1 = self.strategy_params.get("partial_take_profit_1", 0.10)
        partial_2 = self.strategy_params.get("partial_take_profit_2", 0.16)
        breakeven_activation = self.strategy_params.get("breakeven_activation", 0.06)
        max_hold_days = self.strategy_params.get("max_hold_days", 60)

        if risk_config.use_atr_stop_loss or risk_config.use_atr_trailing_stop:
            current_atr = self._calculate_current_atr()
            if current_atr is not None:
                self.position_manager.update_position_atr(self.symbol, current_atr)

        trailing_activation = self.strategy_params.get("trailing_stop_activation", 0.15)
        for position in self.position_manager.get_positions(self.symbol):
            profit_ratio = position.get_unrealized_profit_rate(current_price)
            if profit_ratio >= breakeven_activation:
                position.breakeven_armed = True
            if profit_ratio >= trailing_activation:
                position.trailing_stop_activated = True

        await self._apply_partial_take_profits(date, current_price, partial_1, partial_2)

        for position in list(self.position_manager.get_positions(self.symbol)):
            if self.position_manager.check_breakeven(position, current_price):
                await self._close_position_lot(
                    position, date, current_price, GoldenCrossRiskExitReason.BREAKEVEN.value
                )
                continue
            if (
                risk_config.use_stop_loss
                and risk_config.stop_loss_ratio is not None
                and self.position_manager.check_stop_loss(
                    position, current_price, risk_config.stop_loss_ratio
                )
            ):
                await self._close_position_lot(
                    position, date, current_price, GoldenCrossRiskExitReason.STOP_LOSS.value
                )
                continue
            if (
                risk_config.use_trailing_stop
                and risk_config.trailing_stop_ratio is not None
                and position.trailing_stop_activated
                and self.position_manager.check_trailing_stop(
                    position, current_price, risk_config.trailing_stop_ratio
                )
            ):
                await self._close_position_lot(
                    position, date, current_price, GoldenCrossRiskExitReason.TRAILING_STOP.value
                )
                continue
            if (
                risk_config.use_take_profit
                and risk_config.take_profit_ratio is not None
                and self.position_manager.check_take_profit(
                    position, current_price, risk_config.take_profit_ratio
                )
            ):
                await self._close_position_lot(
                    position, date, current_price, GoldenCrossRiskExitReason.TAKE_PROFIT.value
                )
                continue
            if risk_config.use_atr_stop_loss and self.position_manager.check_atr_stop_loss(
                position, current_price, risk_config.atr_stop_loss_multiplier
            ):
                await self._close_position_lot(
                    position, date, current_price, GoldenCrossRiskExitReason.STOP_LOSS.value
                )
                continue
            if risk_config.use_atr_trailing_stop and self.position_manager.check_atr_trailing_stop(
                position, current_price, risk_config.atr_trailing_multiplier
            ):
                await self._close_position_lot(
                    position, date, current_price, GoldenCrossRiskExitReason.TRAILING_STOP.value
                )
                continue
            if self.position_manager.check_max_hold_days(position, date, max_hold_days):
                await self._close_position_lot(
                    position, date, current_price, GoldenCrossRiskExitReason.MAX_HOLD.value
                )

    async def _apply_partial_take_profits(
        self, date: datetime, current_price: Decimal, partial_1: float, partial_2: float
    ) -> None:
        """포지션 단위 부분익절: 단계별로 **가장 앞 tranche 1개**만 청산한다.

        - 1차(partial_1 도달): 첫 lot 청산 → stage 1
        - 2차(partial_2 도달): 다음 lot 청산 → stage 2
        - 마지막 lot(러너)은 부분익절로 청산하지 않고 트레일링/손절/보유기간 규칙을 따른다.
        수익률은 포지션 평균 진입가 기준이다.
        """
        avg_entry = self.position_manager.get_average_entry_price(self.symbol)
        if avg_entry is None or avg_entry <= 0:
            return
        profit_ratio = float((current_price - avg_entry) / avg_entry)
        stage = self.partial_tp_stage.get(self.symbol, 0)
        steps = (
            (1, partial_1, GoldenCrossRiskExitReason.PARTIAL_TAKE_PROFIT_1.value),
            (2, partial_2, GoldenCrossRiskExitReason.PARTIAL_TAKE_PROFIT_2.value),
        )
        for target_stage, threshold, reason in steps:
            if stage >= target_stage or profit_ratio < threshold:
                continue
            lots = self.position_manager.get_positions(self.symbol)
            if len(lots) <= 1:
                # 러너(마지막 tranche)는 부분익절 대상이 아니다.
                break
            stage = target_stage
            self.partial_tp_stage[self.symbol] = stage
            await self._close_position_lot(lots[0], date, current_price, reason)

    def _apply_final_liquidation_mark(self) -> None:
        """최종 바 평가를 청산 순수령액(슬리피지·수수료·세금 차감)으로 보정한다.

        미청산 lot을 종가 그대로 평가하면 실제 청산 시 비용이 누락되어 최종 자본/MDD가
        낙관된다. 거래 기록(trades)은 바꾸지 않고 마지막 equity 포인트만 보정한다.
        """
        if (
            not self.position_manager.has_position(self.symbol)
            or self.last_bar_date is None
            or self.last_bar_price is None
            or not self.equity_curve
            or not self.daily_stats
        ):
            return
        quantity = self.position_manager.get_total_quantity(self.symbol)
        net_value = self.order_manager.liquidation_value(
            self.symbol, self.last_bar_price, quantity, self.last_bar_date
        )
        last = self.daily_stats[-1]
        self.equity_curve.pop()
        self.daily_stats.pop()
        self._update_daily_stats(last.date, net_value)

    def _update_daily_stats(self, date: datetime, position_value: Decimal) -> None:
        equity = self.cash + position_value
        self.equity_curve.append(equity)
        daily_return = 0.0
        if len(self.equity_curve) > 1:
            prev_equity = self.equity_curve[-2]
            daily_return = (
                float((equity - prev_equity) / prev_equity * 100) if prev_equity > 0 else 0.0
            )
        cumulative_return = float((equity - self.initial_capital) / self.initial_capital * 100)
        equity_array = [float(e) for e in self.equity_curve]
        cummax = max(equity_array) if equity_array else 0.0
        drawdown = (
            float((equity - Decimal(str(cummax))) / Decimal(str(cummax)) * 100)
            if cummax > 0
            else 0.0
        )
        self.daily_stats.append(
            DailyStatsDTO(
                date=date,
                equity=equity,
                cash=self.cash,
                position_value=position_value,
                daily_return=daily_return,
                cumulative_return=cumulative_return,
                drawdown=drawdown,
            )
        )

    def _generate_result(self, start_date: datetime, end_date: datetime) -> BacktestResultDTO:
        # 성과 집계는 result_builder(단일 출처)에 위임한다. 패리티 백테스트와
        # 동일한 계산 경로를 공유하기 위함이며, 행위는 기존과 동일하다.
        return build_backtest_result(
            symbol=self.symbol,
            start_date=start_date,
            end_date=end_date,
            initial_capital=self.initial_capital,
            execution_timing=self.backtest_config.execution_timing,
            equity_curve=self.equity_curve,
            daily_stats=self.daily_stats,
            trades=self.trades,
            completed_trades=self.completed_trades,
        )
