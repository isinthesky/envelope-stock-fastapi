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
            }
        )
        self.last_exit_date = date

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

        for position in list(self.position_manager.get_positions(self.symbol)):
            profit_ratio = position.get_unrealized_profit_rate(current_price)
            if profit_ratio >= breakeven_activation:
                position.breakeven_armed = True
            if profit_ratio >= self.strategy_params.get("trailing_stop_activation", 0.15):
                position.trailing_stop_activated = True

            if not position.partial_take_profit_1_taken and profit_ratio >= partial_1:
                position.partial_take_profit_1_taken = True
                await self._close_position_lot(
                    position,
                    date,
                    current_price,
                    GoldenCrossRiskExitReason.PARTIAL_TAKE_PROFIT_1.value,
                )
                continue
            if not position.partial_take_profit_2_taken and profit_ratio >= partial_2:
                position.partial_take_profit_2_taken = True
                await self._close_position_lot(
                    position,
                    date,
                    current_price,
                    GoldenCrossRiskExitReason.PARTIAL_TAKE_PROFIT_2.value,
                )
                continue
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
