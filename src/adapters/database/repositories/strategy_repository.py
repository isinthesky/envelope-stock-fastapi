# -*- coding: utf-8 -*-
"""
Strategy Repository - 전략 데이터 접근 계층
"""

from datetime import datetime
from typing import Sequence

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.database.models.strategy import StrategyModel, StrategyStatus
from src.adapters.database.repositories.base_repository import (
    BaseRepository,
    PaginationMixin,
    SearchableMixin,
    StatsMixin,
)


class StrategyRepository(
    BaseRepository[StrategyModel], SearchableMixin, PaginationMixin, StatsMixin
):
    """전략 Repository"""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(StrategyModel, session)

    # ==================== 전략 조회 (도메인 특화) ====================

    async def get_by_name(self, name: str) -> StrategyModel | None:
        """전략명으로 조회"""
        return await self.get_one(name=name)

    async def get_by_account(
        self, account_no: str, limit: int = 100, offset: int = 0
    ) -> Sequence[StrategyModel]:
        """계좌번호로 전략 목록 조회"""
        return await self.get_many(limit=limit, offset=offset, account_no=account_no)

    async def get_by_status(
        self, status: StrategyStatus, limit: int = 100, offset: int = 0
    ) -> Sequence[StrategyModel]:
        """상태별 전략 목록 조회"""
        return await self.get_many(limit=limit, offset=offset, status=status.value)

    async def get_active_strategies(
        self, account_no: str | None = None, limit: int = 100
    ) -> Sequence[StrategyModel]:
        """활성 전략 조회"""
        stmt = select(self.model).where(self.model.status == StrategyStatus.ACTIVE.value)
        if account_no:
            stmt = stmt.where(self.model.account_no == account_no)
        stmt = stmt.limit(limit)

        return await self.search(stmt, limit=limit)

    async def get_by_symbol(
        self, symbol: str, limit: int = 100, offset: int = 0
    ) -> Sequence[StrategyModel]:
        """종목 코드로 전략 조회 (symbols 필드에서 검색)"""
        stmt = select(self.model).where(self.model.symbols.like(f"%{symbol}%"))
        stmt = stmt.limit(limit).offset(offset)

        result = await self.session.execute(stmt)
        return result.scalars().all()

    # ==================== 전략 통계 ====================

    async def count_by_status(self, account_no: str, status: StrategyStatus) -> int:
        """계좌별 상태별 전략 수"""
        return await self.count(account_no=account_no, status=status.value)

    async def get_total_executions(self, account_no: str) -> int:
        """계좌의 총 실행 횟수"""
        result = await self.aggregate("total_executions", "sum", account_no=account_no)
        return int(result or 0)

    # ==================== 전략 상태 업데이트 ====================

    async def activate_strategy(self, strategy_id: int) -> None:
        """전략 활성화"""
        await self.update(
            strategy_id,
            status=StrategyStatus.ACTIVE.value,
            started_at=datetime.now(),
        )

    async def pause_strategy(self, strategy_id: int) -> None:
        """전략 일시정지"""
        await self.update(strategy_id, status=StrategyStatus.PAUSED.value)

    async def stop_strategy(self, strategy_id: int) -> None:
        """전략 중지"""
        await self.update(
            strategy_id,
            status=StrategyStatus.STOPPED.value,
            stopped_at=datetime.now(),
        )

    async def update_execution_stats(
        self, strategy_id: int, success: bool
    ) -> None:
        """실행 통계 업데이트"""
        strategy = await self.get_by_id(strategy_id)
        if not strategy:
            return

        total_executions = strategy.total_executions + 1
        successful_executions = strategy.successful_executions + (1 if success else 0)
        failed_executions = strategy.failed_executions + (0 if success else 1)

        await self.update(
            strategy_id,
            total_executions=total_executions,
            successful_executions=successful_executions,
            failed_executions=failed_executions,
            last_executed_at=datetime.now(),
        )
