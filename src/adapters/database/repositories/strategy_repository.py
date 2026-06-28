# -*- coding: utf-8 -*-
"""
Strategy Repository - 전략 데이터 접근 계층

세션 계약 (2026-01-14 업데이트):
- 새 패턴: 생성자에서 session 받지 않고, 메서드 파라미터로 전달
- 기존 패턴: 하위 호환을 위해 생성자에서 session 받는 것도 지원
"""

from datetime import datetime
from typing import Sequence

from sqlalchemy import func, select
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
    """
    전략 Repository

    세션 계약:
    - 새 패턴: __init__에서 session 없이 생성, 메서드에서 session 파라미터로 전달
    - 기존 패턴: __init__에서 session 전달 (하위 호환)
    """

    def __init__(self, session: AsyncSession | None = None) -> None:
        super().__init__(StrategyModel, session)

    # ==================== 전략 조회 (도메인 특화) ====================

    async def get_by_id(
        self,
        id: int,
        session: AsyncSession | None = None,
        include_deleted: bool = False,
    ) -> StrategyModel | None:
        """ID로 전략 조회 (기본: soft deleted 제외)"""
        if include_deleted:
            return await super().get_by_id(id=id, session=session)

        db = self._get_session(session)
        stmt = select(self.model).where(
            self.model.id == id,
            self.model.deleted_at.is_(None),
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_name(
        self,
        name: str,
        account_no: str | None = None,
        session: AsyncSession | None = None,
    ) -> StrategyModel | None:
        """전략명으로 조회"""
        db = self._get_session(session)
        stmt = select(self.model).where(
            self.model.name == name,
            self.model.deleted_at.is_(None),
        )
        if account_no:
            stmt = stmt.where(self.model.account_no == account_no)

        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_account(
        self,
        account_no: str,
        limit: int = 100,
        offset: int = 0,
        session: AsyncSession | None = None,
    ) -> Sequence[StrategyModel]:
        """계좌번호로 전략 목록 조회"""
        db = self._get_session(session)
        stmt = (
            select(self.model)
            .where(
                self.model.account_no == account_no,
                self.model.deleted_at.is_(None),
            )
            .limit(limit)
            .offset(offset)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_by_status(
        self,
        status: StrategyStatus,
        account_no: str | None = None,
        limit: int = 100,
        offset: int = 0,
        session: AsyncSession | None = None,
    ) -> Sequence[StrategyModel]:
        """상태별 전략 목록 조회"""
        db = self._get_session(session)
        conditions = [
            self.model.status == status.value,
            self.model.deleted_at.is_(None),
        ]
        if account_no:
            conditions.append(self.model.account_no == account_no)
        stmt = (
            select(self.model)
            .where(*conditions)
            .limit(limit)
            .offset(offset)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def count_by_account(
        self,
        account_no: str,
        status: StrategyStatus | None = None,
        session: AsyncSession | None = None,
    ) -> int:
        """계좌의 전략 총 개수 조회"""
        db = self._get_session(session)
        conditions = [
            self.model.account_no == account_no,
            self.model.deleted_at.is_(None),
        ]
        if status:
            conditions.append(self.model.status == status.value)
        stmt = select(func.count()).select_from(self.model).where(*conditions)
        result = await db.execute(stmt)
        return result.scalar_one()

    async def get_active_strategies(
        self,
        account_no: str | None = None,
        limit: int = 100,
        session: AsyncSession | None = None,
    ) -> Sequence[StrategyModel]:
        """활성 전략 조회"""
        stmt = select(self.model).where(
            self.model.status == StrategyStatus.ACTIVE.value,
            self.model.deleted_at.is_(None),
        )
        if account_no:
            stmt = stmt.where(self.model.account_no == account_no)
        stmt = stmt.limit(limit)

        return await self.search(stmt, limit=limit, session=session)

    async def get_by_symbol(
        self,
        symbol: str,
        account_no: str | None = None,
        limit: int = 100,
        offset: int = 0,
        session: AsyncSession | None = None,
    ) -> Sequence[StrategyModel]:
        """종목 코드로 전략 조회 (symbols 필드 정확 매칭)"""
        db = self._get_session(session)
        # 종목코드는 콤마 구분 목록 내 단어 단위로 매칭 (부분 문자열 오탐 방지)
        conditions = [
            (
                self.model.symbols.like(f"{symbol},%")
                | self.model.symbols.like(f"%,{symbol},%")
                | self.model.symbols.like(f"%,{symbol}")
                | (self.model.symbols == symbol)
            ),
            self.model.deleted_at.is_(None),
        ]
        if account_no:
            conditions.append(self.model.account_no == account_no)
        stmt = select(self.model).where(*conditions).limit(limit).offset(offset)

        result = await db.execute(stmt)
        return result.scalars().all()

    # ==================== 전략 통계 ====================

    async def count_by_status(
        self,
        account_no: str,
        status: StrategyStatus,
        session: AsyncSession | None = None,
    ) -> int:
        """계좌별 상태별 전략 수"""
        return await self.count(session=session, account_no=account_no, status=status.value)

    async def get_total_executions(
        self, account_no: str, session: AsyncSession | None = None
    ) -> int:
        """계좌의 총 실행 횟수"""
        result = await self.aggregate(
            "total_executions", "sum", session=session, account_no=account_no
        )
        return int(result or 0)

    # ==================== 전략 상태 업데이트 ====================

    async def activate_strategy(
        self, strategy_id: int, session: AsyncSession | None = None
    ) -> None:
        """전략 활성화"""
        await self.update_by_id(
            strategy_id,
            session=session,
            status=StrategyStatus.ACTIVE.value,
            started_at=datetime.now(),
        )

    async def pause_strategy(
        self, strategy_id: int, session: AsyncSession | None = None
    ) -> None:
        """전략 일시정지"""
        await self.update_by_id(strategy_id, session=session, status=StrategyStatus.PAUSED.value)

    async def stop_strategy(
        self, strategy_id: int, session: AsyncSession | None = None
    ) -> None:
        """전략 중지"""
        await self.update_by_id(
            strategy_id,
            session=session,
            status=StrategyStatus.STOPPED.value,
            stopped_at=datetime.now(),
        )

    async def update_execution_stats(
        self, strategy_id: int, success: bool, session: AsyncSession | None = None
    ) -> None:
        """실행 통계 업데이트"""
        strategy = await self.get_by_id(strategy_id, session=session)
        if not strategy:
            return

        total_executions = strategy.total_executions + 1
        successful_executions = strategy.successful_executions + (1 if success else 0)
        failed_executions = strategy.failed_executions + (0 if success else 1)

        await self.update_by_id(
            strategy_id,
            session=session,
            total_executions=total_executions,
            successful_executions=successful_executions,
            failed_executions=failed_executions,
            last_executed_at=datetime.now(),
        )

    async def soft_delete_by_id(
        self, strategy_id: int, session: AsyncSession | None = None
    ) -> StrategyModel | None:
        """전략 소프트 삭제 (deleted_at 설정)"""
        return await self.update_by_id(
            strategy_id,
            session=session,
            deleted_at=datetime.now(),
        )
