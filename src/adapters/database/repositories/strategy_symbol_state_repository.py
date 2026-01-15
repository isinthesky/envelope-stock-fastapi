# -*- coding: utf-8 -*-
"""
Strategy Symbol State Repository - 종목별 상태 Repository

세션 계약 (2026-01-14 업데이트):
- 생성자에서 session은 Optional (하위 호환성 유지)
- 모든 메서드는 session을 첫 번째 파라미터로 받거나 생성자 session 사용
"""

from datetime import datetime
from decimal import Decimal
from typing import Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.database.models.strategy_symbol_state import (
    StrategySymbolStateModel,
    SymbolState,
)
from src.adapters.database.repositories.base_repository import BaseRepository


class StrategySymbolStateRepository(BaseRepository[StrategySymbolStateModel]):
    """종목별 전략 상태 Repository"""

    def __init__(self, session: AsyncSession | None = None) -> None:
        super().__init__(StrategySymbolStateModel, session)

    async def get_by_strategy_and_symbol(
        self,
        strategy_id: int,
        symbol: str,
        session: AsyncSession | None = None,
    ) -> StrategySymbolStateModel | None:
        """전략 ID와 종목코드로 상태 조회"""
        db = self._get_session(session)
        stmt = select(self.model).where(
            self.model.strategy_id == strategy_id,
            self.model.symbol == symbol,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_all_by_strategy(
        self,
        strategy_id: int,
        session: AsyncSession | None = None,
    ) -> Sequence[StrategySymbolStateModel]:
        """전략의 모든 종목 상태 조회"""
        db = self._get_session(session)
        stmt = select(self.model).where(
            self.model.strategy_id == strategy_id
        ).order_by(self.model.symbol)
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_by_state(
        self,
        strategy_id: int,
        state: SymbolState,
        session: AsyncSession | None = None,
    ) -> Sequence[StrategySymbolStateModel]:
        """특정 상태의 종목들 조회"""
        db = self._get_session(session)
        stmt = select(self.model).where(
            self.model.strategy_id == strategy_id,
            self.model.state == state.value,
        ).order_by(self.model.symbol)
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_in_position(
        self,
        strategy_id: int,
        session: AsyncSession | None = None,
    ) -> Sequence[StrategySymbolStateModel]:
        """포지션 보유 중인 종목들 조회"""
        return await self.get_by_state(strategy_id, SymbolState.IN_POSITION, session)

    async def get_ready_to_buy(
        self,
        strategy_id: int,
        session: AsyncSession | None = None,
    ) -> Sequence[StrategySymbolStateModel]:
        """매수 준비 상태 종목들 조회"""
        return await self.get_by_state(strategy_id, SymbolState.READY_TO_BUY, session)

    async def upsert(
        self,
        strategy_id: int,
        symbol: str,
        session: AsyncSession | None = None,
        **kwargs,
    ) -> StrategySymbolStateModel:
        """상태 Upsert (없으면 생성, 있으면 업데이트)"""
        db = self._get_session(session)
        existing = await self.get_by_strategy_and_symbol(strategy_id, symbol, session=db)

        if existing:
            for key, value in kwargs.items():
                setattr(existing, key, value)
            await db.flush()
            await db.refresh(existing)
            return existing
        else:
            return await self.create(
                session=db,
                strategy_id=strategy_id,
                symbol=symbol,
                **kwargs,
            )

    async def update_state(
        self,
        strategy_id: int,
        symbol: str,
        new_state: SymbolState,
        gc_date: datetime | None = None,
        pullback_date: datetime | None = None,
        entry_date: datetime | None = None,
        entry_price: Decimal | None = None,
        quantity: int | None = None,
        session: AsyncSession | None = None,
    ) -> StrategySymbolStateModel | None:
        """상태 전이 업데이트"""
        db = self._get_session(session)
        state = await self.get_by_strategy_and_symbol(strategy_id, symbol, session=db)
        if not state:
            return None

        state.state = new_state.value

        if gc_date is not None:
            state.gc_date = gc_date
        if pullback_date is not None:
            state.pullback_date = pullback_date
        if entry_date is not None:
            state.entry_date = entry_date
        if entry_price is not None:
            state.entry_price = entry_price
        if quantity is not None:
            state.quantity = quantity

        state.last_checked_at = datetime.now()

        await db.flush()
        await db.refresh(state)
        return state

    async def update_indicators(
        self,
        strategy_id: int,
        symbol: str,
        ma_short: Decimal,
        ma_long: Decimal,
        stoch_k: Decimal,
        stoch_d: Decimal,
        close: Decimal,
        session: AsyncSession | None = None,
    ) -> StrategySymbolStateModel | None:
        """지표 스냅샷 업데이트"""
        db = self._get_session(session)
        state = await self.get_by_strategy_and_symbol(strategy_id, symbol, session=db)
        if not state:
            return None

        state.last_ma_short = ma_short
        state.last_ma_long = ma_long
        state.last_stoch_k = stoch_k
        state.last_stoch_d = stoch_d
        state.last_close = close
        state.last_checked_at = datetime.now()

        await db.flush()
        await db.refresh(state)
        return state

    async def reset_to_waiting(
        self,
        strategy_id: int,
        symbol: str,
        session: AsyncSession | None = None,
    ) -> StrategySymbolStateModel | None:
        """상태를 초기 상태로 리셋"""
        db = self._get_session(session)
        state = await self.get_by_strategy_and_symbol(strategy_id, symbol, session=db)
        if not state:
            return None

        state.state = SymbolState.WAITING_FOR_GC.value
        state.gc_date = None
        state.pullback_date = None
        state.entry_date = None
        state.entry_price = None
        state.quantity = None
        # 트레일링 스탑 관련 필드 리셋
        state.highest_price = None
        state.trailing_stop_activated = False
        state.trailing_stop_activated_at = None
        state.last_checked_at = datetime.now()

        await db.flush()
        await db.refresh(state)
        return state

    async def update_highest_price(
        self,
        strategy_id: int,
        symbol: str,
        highest_price: Decimal,
        session: AsyncSession | None = None,
    ) -> StrategySymbolStateModel | None:
        """포지션 최고가 업데이트"""
        db = self._get_session(session)
        state = await self.get_by_strategy_and_symbol(strategy_id, symbol, session=db)
        if not state:
            return None

        state.highest_price = highest_price
        state.last_checked_at = datetime.now()

        await db.flush()
        await db.refresh(state)
        return state

    async def activate_trailing_stop(
        self,
        strategy_id: int,
        symbol: str,
        session: AsyncSession | None = None,
    ) -> StrategySymbolStateModel | None:
        """트레일링 스탑 활성화"""
        db = self._get_session(session)
        state = await self.get_by_strategy_and_symbol(strategy_id, symbol, session=db)
        if not state:
            return None

        state.trailing_stop_activated = True
        state.trailing_stop_activated_at = datetime.now()
        state.last_checked_at = datetime.now()

        await db.flush()
        await db.refresh(state)
        return state

    async def init_position_tracking(
        self,
        strategy_id: int,
        symbol: str,
        entry_price: Decimal,
        session: AsyncSession | None = None,
    ) -> StrategySymbolStateModel | None:
        """포지션 진입 시 트래킹 초기화"""
        db = self._get_session(session)
        state = await self.get_by_strategy_and_symbol(strategy_id, symbol, session=db)
        if not state:
            return None

        state.highest_price = entry_price
        state.trailing_stop_activated = False
        state.trailing_stop_activated_at = None
        state.last_checked_at = datetime.now()

        await db.flush()
        await db.refresh(state)
        return state

    async def delete_by_strategy(
        self,
        strategy_id: int,
        session: AsyncSession | None = None,
    ) -> int:
        """전략의 모든 종목 상태 삭제"""
        return await self.delete_many(session=session, strategy_id=strategy_id)

    async def count_by_state(
        self,
        strategy_id: int,
        session: AsyncSession | None = None,
    ) -> dict[str, int]:
        """상태별 종목 수 카운트"""
        result = {}
        for state in SymbolState:
            count = await self.count(session=session, strategy_id=strategy_id, state=state.value)
            result[state.value] = count
        return result
