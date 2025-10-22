# -*- coding: utf-8 -*-
"""
Order Manager - 주문 관리자

백테스팅 시 가상 주문 실행을 담당합니다.
"""

from datetime import datetime
from decimal import Decimal

from src.application.domain.backtest.dto import BacktestConfigDTO, TradeDTO


class BacktestOrderManager:
    """백테스팅 주문 관리자"""

    def __init__(self, config: BacktestConfigDTO):
        """
        Args:
            config: 백테스팅 설정
        """
        self.config = config
        self.trade_id_counter = 0

    def execute_buy_order(
        self,
        symbol: str,
        price: Decimal,
        quantity: int,
        date: datetime
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

        # 슬리피지 적용
        if self.config.use_slippage:
            actual_price = price * Decimal(str(1 + self.config.slippage_rate))
        else:
            actual_price = price

        # 매수 금액
        purchase_amount = actual_price * quantity

        # 수수료 계산
        if self.config.use_commission:
            commission = purchase_amount * Decimal(str(self.config.commission_rate))
        else:
            commission = Decimal("0")

        # 총 비용
        total_cost = purchase_amount + commission

        # Trade DTO 생성
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
            tax=Decimal("0"),  # 매수 시 세금 없음
            profit=None,
            profit_rate=None,
            holding_days=None,
            exit_reason=None
        )

        return trade, total_cost

    def execute_sell_order(
        self,
        trade: TradeDTO,
        price: Decimal,
        date: datetime,
        exit_reason: str = "signal"
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
        # 슬리피지 적용
        if self.config.use_slippage:
            actual_price = price * Decimal(str(1 - self.config.slippage_rate))
        else:
            actual_price = price

        # 매도 금액
        sell_amount = actual_price * trade.quantity

        # 수수료 계산
        if self.config.use_commission:
            commission = sell_amount * Decimal(str(self.config.commission_rate))
        else:
            commission = Decimal("0")

        # 증권거래세 계산
        if self.config.use_tax:
            tax = sell_amount * Decimal(str(self.config.tax_rate))
        else:
            tax = Decimal("0")

        # 순 수익 계산
        net_proceeds = sell_amount - commission - tax

        # 매수 비용 (매수 수수료 포함)
        purchase_cost = trade.entry_price * trade.quantity + trade.commission

        # 손익
        profit = net_proceeds - purchase_cost

        # 손익률
        profit_rate = float(profit / purchase_cost * 100) if purchase_cost > 0 else 0.0

        # 보유 기간
        holding_days = (date - trade.entry_date).days

        # Trade DTO 업데이트
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
            exit_reason=exit_reason
        )

        return updated_trade, net_proceeds

    def calculate_position_size(
        self,
        available_cash: Decimal,
        allocation_ratio: float,
        current_price: Decimal
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

        # 할당 금액
        target_amount = available_cash * Decimal(str(allocation_ratio))

        # 수량 계산 (수수료 고려)
        if self.config.use_commission:
            commission_multiplier = Decimal(str(1 + self.config.commission_rate))
            affordable_amount = target_amount / commission_multiplier
        else:
            affordable_amount = target_amount

        quantity = int(affordable_amount / current_price)

        return quantity

    def can_afford(
        self,
        available_cash: Decimal,
        price: Decimal,
        quantity: int
    ) -> bool:
        """
        매수 가능 여부 확인

        Args:
            available_cash: 사용 가능한 현금
            price: 매수 가격
            quantity: 수량

        Returns:
            bool: 매수 가능 여부
        """
        # 예상 비용 계산
        purchase_amount = price * quantity

        if self.config.use_commission:
            commission = purchase_amount * Decimal(str(self.config.commission_rate))
        else:
            commission = Decimal("0")

        total_cost = purchase_amount + commission

        return available_cash >= total_cost
