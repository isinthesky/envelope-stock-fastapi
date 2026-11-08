# -*- coding: utf-8 -*-
"""
Order Manager - 주문 관리자

백테스팅 시 가상 주문 실행을 담당합니다.
"""

from datetime import datetime
from decimal import Decimal

from src.application.domain.backtest.cost_schedule import (
    BacktestCostSchedule,
    get_backtest_cost_schedule,
    get_latest_backtest_cost_schedule,
)
from src.application.domain.backtest.dto import BacktestConfigDTO, TradeDTO
from src.settings.config import settings


class BacktestOrderManager:
    """백테스팅 주문 관리자"""

    def __init__(self, config: BacktestConfigDTO):
        """
        Args:
            config: 백테스팅 설정
        """
        self.config = config
        self.trade_id_counter = 0
        exempt = (
            config.tax_exempt_symbols
            if config.tax_exempt_symbols is not None
            else settings.etf_universe_symbols
        )
        self._tax_exempt_symbols: frozenset[str] = frozenset(
            s.strip() for s in exempt if s and s.strip()
        )

    def is_tax_exempt(self, symbol: str) -> bool:
        """국내 상장 ETF는 증권거래세 면제 → 매도세 0%."""
        return self.config.etf_tax_exempt and symbol in self._tax_exempt_symbols

    def _cost_schedule_for(self, trade_datetime: datetime) -> BacktestCostSchedule:
        schedule_date = self.config.cost_schedule_date or trade_datetime.date()
        return get_backtest_cost_schedule(schedule_date)

    def _cost_schedule_for_estimate(self) -> BacktestCostSchedule:
        if self.config.cost_schedule_date is not None:
            return get_backtest_cost_schedule(self.config.cost_schedule_date)
        return get_latest_backtest_cost_schedule()

    def _commission_rate(self, schedule: BacktestCostSchedule) -> Decimal:
        if self.config.commission_rate is not None:
            return Decimal(str(self.config.commission_rate))
        return schedule.default_commission_rate

    def _sell_tax_rate(self, schedule: BacktestCostSchedule, symbol: str | None = None) -> Decimal:
        if symbol is not None and self.is_tax_exempt(symbol):
            return Decimal("0")
        if self.config.tax_rate is not None:
            return Decimal(str(self.config.tax_rate))
        return schedule.sell_tax_rate

    def _slippage_rate(self, schedule: BacktestCostSchedule) -> Decimal:
        base = (
            Decimal(str(self.config.slippage_rate))
            if self.config.slippage_rate is not None
            else schedule.default_slippage_rate
        )
        return base * Decimal(str(self.config.slippage_multiplier))

    def _round_execution_price(
        self,
        schedule: BacktestCostSchedule,
        price: Decimal,
    ) -> Decimal:
        if self.config.use_price_rounding:
            return schedule.round_price(price)
        return price

    # ==================== 공개 비용 헬퍼(포트폴리오 시뮬레이션/청산평가용) ====================

    def buy_commission(self, amount: Decimal, trade_date: datetime) -> Decimal:
        """매수 체결금액에 대한 수수료."""
        if not self.config.use_commission:
            return Decimal("0")
        return amount * self._commission_rate(self._cost_schedule_for(trade_date))

    def sell_costs(self, amount: Decimal, trade_date: datetime, symbol: str) -> Decimal:
        """매도 체결금액에 대한 수수료 + 매도세(ETF 면제 반영)."""
        schedule = self._cost_schedule_for(trade_date)
        commission = (
            amount * self._commission_rate(schedule) if self.config.use_commission else Decimal("0")
        )
        tax = (
            amount * self._sell_tax_rate(schedule, symbol) if self.config.use_tax else Decimal("0")
        )
        return commission + tax

    def sell_execution_price(self, price: Decimal, trade_date: datetime) -> Decimal:
        """매도 슬리피지/호가 반올림을 반영한 체결가."""
        schedule = self._cost_schedule_for(trade_date)
        actual = price
        if self.config.use_slippage:
            actual = price * (Decimal("1") - self._slippage_rate(schedule))
        return self._round_execution_price(schedule, actual)

    def liquidation_value(
        self, symbol: str, price: Decimal, quantity: int, trade_date: datetime
    ) -> Decimal:
        """보유 수량을 해당 바 종가로 청산했을 때의 순수령액(슬리피지·수수료·세금 차감)."""
        if quantity <= 0:
            return Decimal("0")
        amount = self.sell_execution_price(price, trade_date) * quantity
        return amount - self.sell_costs(amount, trade_date, symbol)

    def execute_buy_order(
        self, symbol: str, price: Decimal, quantity: int, date: datetime
    ) -> tuple[TradeDTO, Decimal]:
        """
        매수 주문 실행

        Args:
            symbol: 종목코드
            price: 매수 가격
            quantity: 수량
            date: 거래일

        Returns:
            tuple[TradeDTO, Decimal]: (거래 정보, 총 비용)
        """
        self.trade_id_counter += 1
        schedule = self._cost_schedule_for(date)
        slippage_rate = self._slippage_rate(schedule)

        if self.config.use_slippage:
            actual_price = price * (Decimal("1") + slippage_rate)
        else:
            actual_price = price
        actual_price = self._round_execution_price(schedule, actual_price)

        purchase_amount = actual_price * quantity

        if self.config.use_commission:
            commission = purchase_amount * self._commission_rate(schedule)
        else:
            commission = Decimal("0")

        total_cost = purchase_amount + commission

        trade = TradeDTO(
            trade_id=self.trade_id_counter,
            symbol=symbol,
            trade_type="buy",
            entry_date=date,
            entry_price=actual_price,
            exit_date=None,
            exit_price=None,
            quantity=quantity,
            commission=commission,
            tax=Decimal("0"),
            profit=None,
            profit_rate=None,
            holding_days=None,
            exit_reason=None,
        )

        return trade, total_cost

    def execute_sell_order(
        self, trade: TradeDTO, price: Decimal, date: datetime, exit_reason: str = "signal"
    ) -> tuple[TradeDTO, Decimal]:
        """
        매도 주문 실행

        Args:
            trade: 기존 매수 거래 정보
            price: 매도 가격
            date: 거래일
            exit_reason: 청산 이유 (signal/stop_loss/take_profit/trailing_stop)

        Returns:
            tuple[TradeDTO, Decimal]: (업데이트된 거래 정보, 총 수익)
        """
        schedule = self._cost_schedule_for(date)
        slippage_rate = self._slippage_rate(schedule)

        if self.config.use_slippage:
            actual_price = price * (Decimal("1") - slippage_rate)
        else:
            actual_price = price
        actual_price = self._round_execution_price(schedule, actual_price)

        sell_amount = actual_price * trade.quantity

        if self.config.use_commission:
            commission = sell_amount * self._commission_rate(schedule)
        else:
            commission = Decimal("0")

        if self.config.use_tax:
            tax = sell_amount * self._sell_tax_rate(schedule, trade.symbol)
        else:
            tax = Decimal("0")

        net_proceeds = sell_amount - commission - tax

        purchase_cost = trade.entry_price * trade.quantity + trade.commission

        profit = net_proceeds - purchase_cost

        profit_rate = float(profit / purchase_cost * 100) if purchase_cost > 0 else 0.0

        holding_days = (date - trade.entry_date).days

        updated_trade = TradeDTO(
            trade_id=trade.trade_id,
            symbol=trade.symbol,
            trade_type=trade.trade_type,
            entry_date=trade.entry_date,
            entry_price=trade.entry_price,
            exit_date=date,
            exit_price=actual_price,
            quantity=trade.quantity,
            commission=trade.commission + commission,
            tax=tax,
            profit=profit,
            profit_rate=profit_rate,
            holding_days=holding_days,
            exit_reason=exit_reason,
        )

        return updated_trade, net_proceeds

    def calculate_position_size(
        self, available_cash: Decimal, allocation_ratio: float, current_price: Decimal
    ) -> int:
        """
        포지션 크기 계산

        Args:
            available_cash: 사용 가능한 현금
            allocation_ratio: 자산 배분 비율 (0.0 ~ 1.0)
            current_price: 현재 주가

        Returns:
            int: 매수 수량
        """
        if current_price <= 0:
            return 0

        schedule = self._cost_schedule_for_estimate()
        target_amount = available_cash * Decimal(str(allocation_ratio))
        price_with_slippage = current_price
        if self.config.use_slippage:
            price_with_slippage *= Decimal("1") + self._slippage_rate(schedule)
        price_with_slippage = self._round_execution_price(schedule, price_with_slippage)

        if self.config.use_commission:
            commission_multiplier = Decimal("1") + self._commission_rate(schedule)
            affordable_amount = target_amount / commission_multiplier
        else:
            affordable_amount = target_amount

        quantity = int(affordable_amount / price_with_slippage)

        return quantity

    def can_afford(self, available_cash: Decimal, price: Decimal, quantity: int) -> bool:
        """
        매수 가능 여부 확인

        Args:
            available_cash: 사용 가능한 현금
            price: 매수 가격
            quantity: 수량

        Returns:
            bool: 매수 가능 여부
        """
        schedule = self._cost_schedule_for_estimate()
        actual_price = price
        if self.config.use_slippage:
            actual_price *= Decimal("1") + self._slippage_rate(schedule)
        actual_price = self._round_execution_price(schedule, actual_price)
        purchase_amount = actual_price * quantity

        if self.config.use_commission:
            commission = purchase_amount * self._commission_rate(schedule)
        else:
            commission = Decimal("0")

        total_cost = purchase_amount + commission

        return available_cash >= total_cost
