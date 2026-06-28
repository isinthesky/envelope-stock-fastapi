# -*- coding: utf-8 -*-
"""
Position Manager - 포지션 관리자

백테스팅 시 포지션(다중 lot 포함) 관리를 담당합니다.
"""

from datetime import datetime
from decimal import Decimal

from src.application.domain.backtest.dto import PositionDTO, TradeDTO


class Position:
    """개별 lot 포지션 정보"""

    def __init__(
        self,
        symbol: str,
        quantity: int,
        entry_price: Decimal,
        entry_date: datetime,
        trade_id: int,
        entry_atr: float | None = None,
    ):
        self.symbol = symbol
        self.quantity = quantity
        self.entry_price = entry_price
        self.entry_date = entry_date
        self.trade_id = trade_id
        self.highest_price = entry_price
        self.entry_atr = entry_atr
        self.current_atr: float | None = entry_atr
        self.breakeven_armed = False
        self.trailing_stop_activated = False
        self.partial_take_profit_1_taken = False
        self.partial_take_profit_2_taken = False

    def update_highest_price(self, price: Decimal) -> None:
        if price > self.highest_price:
            self.highest_price = price

    def get_unrealized_profit(self, current_price: Decimal) -> Decimal:
        return (current_price - self.entry_price) * self.quantity

    def get_unrealized_profit_rate(self, current_price: Decimal) -> float:
        if self.entry_price == 0:
            return 0.0
        return float((current_price - self.entry_price) / self.entry_price)


class PositionManager:
    """포지션 관리자 (종목별 다중 lot 지원)"""

    def __init__(self):
        self.positions: dict[str, list[Position]] = {}

    def open_position(
        self,
        symbol: str,
        quantity: int,
        entry_price: Decimal,
        entry_date: datetime,
        trade_id: int,
        entry_atr: float | None = None,
    ) -> None:
        lots = self.positions.setdefault(symbol, [])
        lots.append(
            Position(
                symbol=symbol,
                quantity=quantity,
                entry_price=entry_price,
                entry_date=entry_date,
                trade_id=trade_id,
                entry_atr=entry_atr,
            )
        )

    def close_position(self, symbol: str) -> list[Position]:
        return self.positions.pop(symbol, [])

    def close_lot(self, symbol: str, trade_id: int) -> Position | None:
        lots = self.positions.get(symbol, [])
        for idx, lot in enumerate(lots):
            if lot.trade_id == trade_id:
                removed = lots.pop(idx)
                if not lots:
                    self.positions.pop(symbol, None)
                return removed
        return None

    def has_position(self, symbol: str) -> bool:
        return bool(self.positions.get(symbol))

    def get_positions(self, symbol: str) -> list[Position]:
        return list(self.positions.get(symbol, []))

    def get_position(self, symbol: str) -> Position | None:
        lots = self.positions.get(symbol, [])
        return lots[0] if lots else None

    def get_total_quantity(self, symbol: str) -> int:
        return sum(position.quantity for position in self.positions.get(symbol, []))

    def get_average_entry_price(self, symbol: str) -> Decimal | None:
        lots = self.positions.get(symbol, [])
        total_qty = sum(p.quantity for p in lots)
        if total_qty == 0:
            return None
        total_cost = sum(p.entry_price * p.quantity for p in lots)
        return total_cost / total_qty

    def get_latest_entry_date(self, symbol: str) -> datetime | None:
        lots = self.positions.get(symbol, [])
        if not lots:
            return None
        return min(p.entry_date for p in lots)

    def to_dto(self, symbol: str, current_price: Decimal) -> PositionDTO | None:
        if not self.has_position(symbol):
            return None
        quantity = self.get_total_quantity(symbol)
        avg_entry = self.get_average_entry_price(symbol)
        entry_date = self.get_latest_entry_date(symbol)
        if avg_entry is None or entry_date is None:
            return None
        unrealized_profit = (current_price - avg_entry) * quantity
        profit_rate = float((current_price - avg_entry) / avg_entry * 100) if avg_entry else 0.0
        return PositionDTO(
            symbol=symbol,
            quantity=quantity,
            entry_price=avg_entry,
            entry_date=entry_date,
            current_price=current_price,
            unrealized_profit=unrealized_profit,
            unrealized_profit_rate=profit_rate,
        )

    def update_positions(self, current_prices: dict[str, Decimal]) -> Decimal:
        total_value = Decimal('0')
        for symbol, lots in self.positions.items():
            current_price = current_prices.get(symbol)
            if current_price is None:
                continue
            for position in lots:
                position.update_highest_price(current_price)
                total_value += current_price * position.quantity
        return total_value

    def check_stop_loss(self, position: Position, current_price: Decimal, stop_loss_ratio: float) -> bool:
        return position.get_unrealized_profit_rate(current_price) <= stop_loss_ratio

    def check_take_profit(self, position: Position, current_price: Decimal, take_profit_ratio: float) -> bool:
        return position.get_unrealized_profit_rate(current_price) >= take_profit_ratio

    def check_trailing_stop(self, position: Position, current_price: Decimal, trailing_stop_ratio: float) -> bool:
        decline_rate = float((current_price - position.highest_price) / position.highest_price)
        return decline_rate <= -trailing_stop_ratio

    def check_breakeven(self, position: Position, current_price: Decimal) -> bool:
        if not position.breakeven_armed:
            return False
        return current_price <= position.entry_price

    def check_max_hold_days(self, position: Position, date: datetime, max_hold_days: int) -> bool:
        return (date - position.entry_date).days >= max_hold_days

    def check_atr_stop_loss(self, position: Position, current_price: Decimal, atr_multiplier: float = 2.0) -> bool:
        if position.entry_atr is None:
            return False
        stop_price = float(position.entry_price) - (position.entry_atr * atr_multiplier)
        return float(current_price) <= stop_price

    def check_atr_trailing_stop(self, position: Position, current_price: Decimal, atr_multiplier: float = 2.0) -> bool:
        atr = position.current_atr or position.entry_atr
        if atr is None:
            return False
        stop_price = float(position.highest_price) - (atr * atr_multiplier)
        return float(current_price) <= stop_price

    def update_position_atr(self, symbol: str, atr: float) -> None:
        for position in self.positions.get(symbol, []):
            position.current_atr = atr

    def get_all_positions(self) -> dict[str, list[Position]]:
        return {symbol: list(lots) for symbol, lots in self.positions.items()}

    def get_total_position_count(self) -> int:
        return sum(len(lots) for lots in self.positions.values())

    def clear_all_positions(self) -> None:
        self.positions.clear()
