# -*- coding: utf-8 -*-
"""
Order Repository - 주문 데이터 접근 계층
"""

from datetime import datetime
from typing import Sequence

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.database.models.order import OrderModel, OrderStatus
from src.adapters.database.repositories.base_repository import (
    BaseRepository,
    PaginationMixin,
    SearchableMixin,
    StatsMixin,
)


class OrderRepository(BaseRepository[OrderModel], SearchableMixin, PaginationMixin, StatsMixin):
    """주문 Repository"""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(OrderModel, session)

    # ==================== 주문 조회 (도메인 특화) ====================

    async def get_by_order_id(self, order_id: str) -> OrderModel | None:
        """KIS API 주문 ID로 조회"""
        return await self.get_one(order_id=order_id)

    async def get_by_account(
        self, account_no: str, limit: int = 100, offset: int = 0
    ) -> Sequence[OrderModel]:
        """계좌번호로 주문 목록 조회"""
        return await self.get_many(limit=limit, offset=offset, account_no=account_no)

    async def get_by_symbol(
        self, symbol: str, limit: int = 100, offset: int = 0
    ) -> Sequence[OrderModel]:
        """종목코드로 주문 목록 조회"""
        return await self.get_many(limit=limit, offset=offset, symbol=symbol)

    async def get_by_status(
        self, status: OrderStatus, limit: int = 100, offset: int = 0
    ) -> Sequence[OrderModel]:
        """상태별 주문 목록 조회"""
        return await self.get_many(limit=limit, offset=offset, status=status.value)

    async def get_active_orders(
        self, account_no: str | None = None, limit: int = 100
    ) -> Sequence[OrderModel]:
        """활성 주문 조회 (대기, 제출, 부분체결)"""
        stmt = select(self.model).where(
            self.model.status.in_(
                [
                    OrderStatus.PENDING.value,
                    OrderStatus.SUBMITTED.value,
                    OrderStatus.PARTIALLY_FILLED.value,
                ]
            )
        )
        if account_no:
            stmt = stmt.where(self.model.account_no == account_no)
        stmt = stmt.limit(limit)

        return await self.search(stmt, limit=limit)

    async def get_orders_by_date_range(
        self, start_date: datetime, end_date: datetime, account_no: str | None = None
    ) -> Sequence[OrderModel]:
        """날짜 범위로 주문 조회"""
        stmt = select(self.model).where(
            and_(self.model.order_time >= start_date, self.model.order_time <= end_date)
        )
        if account_no:
            stmt = stmt.where(self.model.account_no == account_no)

        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_orders_by_strategy(
        self, strategy_id: int, limit: int = 100, offset: int = 0
    ) -> Sequence[OrderModel]:
        """전략 ID로 주문 조회"""
        return await self.get_many(limit=limit, offset=offset, strategy_id=strategy_id)

    # ==================== 주문 통계 ====================

    async def count_by_status(self, account_no: str, status: OrderStatus) -> int:
        """계좌별 상태별 주문 수"""
        return await self.count(account_no=account_no, status=status.value)

    async def get_total_filled_amount(self, account_no: str) -> float:
        """계좌의 총 체결 금액"""
        result = await self.aggregate("total_cost", "sum", account_no=account_no)
        return float(result or 0)
