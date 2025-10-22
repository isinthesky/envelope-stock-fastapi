# -*- coding: utf-8 -*-
"""
Position Manager - 포지션 관리자

백테스팅 시 포지션 관리를 담당합니다.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from src.application.domain.backtest.dto import PositionDTO, TradeDTO


class Position:
    """포지션 정보"""

    def __init__(
        self,
        symbol: str,
        quantity: int,
        entry_price: Decimal,
        entry_date: datetime,
        trade_id: int
    ):
        """
        Args:
            symbol: 종목코드
            quantity: 수량
            entry_price: 진입 가격
            entry_date: 진입일
            trade_id: 거래 ID
        """
        self.symbol = symbol
        self.quantity = quantity
        self.entry_price = entry_price
        self.entry_date = entry_date
        self.trade_id = trade_id
        self.highest_price = entry_price  # Trailing Stop용

    def update_highest_price(self, price: Decimal) -> None:
        """최고가 업데이트 (Trailing Stop용)"""
        if price > self.highest_price:
            self.highest_price = price

    def get_unrealized_profit(self, current_price: Decimal) -> Decimal:
        """평가 손익 계산"""
        return (current_price - self.entry_price) * self.quantity

    def get_unrealized_profit_rate(self, current_price: Decimal) -> float:
        """평가 손익률 계산 (%)"""
        if self.entry_price == 0:
            return 0.0
        return float((current_price - self.entry_price) / self.entry_price * 100)

    def to_dto(self, current_price: Decimal) -> PositionDTO:
        """DTO로 변환"""
        return PositionDTO(
            symbol=self.symbol,
            quantity=self.quantity,
            entry_price=self.entry_price,
            entry_date=self.entry_date,
            current_price=current_price,
            unrealized_profit=self.get_unrealized_profit(current_price),
            unrealized_profit_rate=self.get_unrealized_profit_rate(current_price)
        )


class PositionManager:
    """포지션 관리자"""

    def __init__(self):
        """포지션 관리자 초기화"""
        self.positions: dict[str, Position] = {}

    def open_position(
        self,
        symbol: str,
        quantity: int,
        entry_price: Decimal,
        entry_date: datetime,
        trade_id: int
    ) -> None:
        """
        포지션 오픈

        Args:
            symbol: 종목코드
            quantity: 수량
            entry_price: 진입 가격
            entry_date: 진입일
            trade_id: 거래 ID
        """
        self.positions[symbol] = Position(
            symbol=symbol,
            quantity=quantity,
            entry_price=entry_price,
            entry_date=entry_date,
            trade_id=trade_id
        )

    def close_position(self, symbol: str) -> Optional[Position]:
        """
        포지션 청산

        Args:
            symbol: 종목코드

        Returns:
            Optional[Position]: 청산된 포지션 (없으면 None)
        """
        return self.positions.pop(symbol, None)

    def has_position(self, symbol: str) -> bool:
        """
        포지션 보유 여부

        Args:
            symbol: 종목코드

        Returns:
            bool: 포지션 보유 여부
        """
        return symbol in self.positions

    def get_position(self, symbol: str) -> Optional[Position]:
        """
        포지션 조회

        Args:
            symbol: 종목코드

        Returns:
            Optional[Position]: 포지션 (없으면 None)
        """
        return self.positions.get(symbol)

    def update_positions(self, current_prices: dict[str, Decimal]) -> Decimal:
        """
        포지션 평가액 업데이트

        Args:
            current_prices: 종목별 현재가 딕셔너리

        Returns:
            Decimal: 총 평가액
        """
        total_value = Decimal("0")

        for symbol, position in self.positions.items():
            current_price = current_prices.get(symbol, position.entry_price)

            # 최고가 업데이트 (Trailing Stop용)
            position.update_highest_price(current_price)

            # 평가액 계산
            position_value = current_price * position.quantity
            total_value += position_value

        return total_value

    def check_stop_loss(
        self,
        symbol: str,
        current_price: Decimal,
        stop_loss_ratio: float
    ) -> bool:
        """
        손절 체크

        Args:
            symbol: 종목코드
            current_price: 현재가
            stop_loss_ratio: 손절 비율 (예: -0.03 = -3%)

        Returns:
            bool: 손절 발동 여부
        """
        position = self.get_position(symbol)
        if not position:
            return False

        profit_rate = position.get_unrealized_profit_rate(current_price)

        return profit_rate <= stop_loss_ratio

    def check_take_profit(
        self,
        symbol: str,
        current_price: Decimal,
        take_profit_ratio: float
    ) -> bool:
        """
        익절 체크

        Args:
            symbol: 종목코드
            current_price: 현재가
            take_profit_ratio: 익절 비율 (예: 0.05 = +5%)

        Returns:
            bool: 익절 발동 여부
        """
        position = self.get_position(symbol)
        if not position:
            return False

        profit_rate = position.get_unrealized_profit_rate(current_price)

        return profit_rate >= take_profit_ratio

    def check_trailing_stop(
        self,
        symbol: str,
        current_price: Decimal,
        trailing_stop_ratio: float
    ) -> bool:
        """
        Trailing Stop 체크

        Args:
            symbol: 종목코드
            current_price: 현재가
            trailing_stop_ratio: Trailing Stop 비율 (예: 0.02 = 2%)

        Returns:
            bool: Trailing Stop 발동 여부
        """
        position = self.get_position(symbol)
        if not position:
            return False

        # 최고가 대비 현재가 하락률
        decline_rate = float(
            (current_price - position.highest_price) / position.highest_price
        )

        return decline_rate <= -trailing_stop_ratio

    def get_all_positions(self) -> dict[str, Position]:
        """모든 포지션 조회"""
        return self.positions.copy()

    def get_total_position_count(self) -> int:
        """총 포지션 수"""
        return len(self.positions)

    def clear_all_positions(self) -> None:
        """모든 포지션 청산"""
        self.positions.clear()
