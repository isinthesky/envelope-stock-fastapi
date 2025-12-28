# -*- coding: utf-8 -*-
"""
Strategy Signal Repository - 전략 시그널 Repository
"""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.database.models.strategy_signal import (
    SignalStatus,
    SignalType,
    StrategySignalModel,
)
from src.adapters.database.repositories.base_repository import (
    BaseRepository,
    PaginationMixin,
)


class StrategySignalRepository(BaseRepository[StrategySignalModel], PaginationMixin):
    """전략 시그널 Repository"""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(StrategySignalModel, session)

    async def create_signal(
        self,
        strategy_id: int,
        symbol: str,
        signal_type: SignalType,
        signal_price: Decimal,
        target_quantity: int | None = None,
        prev_state: str | None = None,
        new_state: str | None = None,
        ma_short: Decimal | None = None,
        ma_long: Decimal | None = None,
        stoch_k: Decimal | None = None,
        stoch_d: Decimal | None = None,
        note: str | None = None,
    ) -> StrategySignalModel:
        """시그널 생성"""
        return await self.create(
            strategy_id=strategy_id,
            symbol=symbol,
            signal_type=signal_type.value,
            signal_status=SignalStatus.PENDING.value,
            signal_price=signal_price,
            target_quantity=target_quantity,
            prev_state=prev_state,
            new_state=new_state,
            ma_short=ma_short,
            ma_long=ma_long,
            stoch_k=stoch_k,
            stoch_d=stoch_d,
            note=note,
            signal_at=datetime.now(),
        )

    async def get_by_strategy(
        self,
        strategy_id: int,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[StrategySignalModel]:
        """전략의 시그널 조회"""
        stmt = (
            select(self.model)
            .where(self.model.strategy_id == strategy_id)
            .order_by(self.model.signal_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_by_symbol(
        self,
        strategy_id: int,
        symbol: str,
        limit: int = 50,
    ) -> Sequence[StrategySignalModel]:
        """종목별 시그널 조회"""
        stmt = (
            select(self.model)
            .where(
                self.model.strategy_id == strategy_id,
                self.model.symbol == symbol,
            )
            .order_by(self.model.signal_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_pending_signals(
        self, strategy_id: int
    ) -> Sequence[StrategySignalModel]:
        """대기 중인 시그널 조회"""
        stmt = (
            select(self.model)
            .where(
                self.model.strategy_id == strategy_id,
                self.model.signal_status == SignalStatus.PENDING.value,
            )
            .order_by(self.model.signal_at)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_recent_signals(
        self,
        strategy_id: int,
        days: int = 7,
    ) -> Sequence[StrategySignalModel]:
        """최근 N일 시그널 조회"""
        since = datetime.now() - timedelta(days=days)
        stmt = (
            select(self.model)
            .where(
                self.model.strategy_id == strategy_id,
                self.model.signal_at >= since,
            )
            .order_by(self.model.signal_at.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def update_execution(
        self,
        signal_id: int,
        status: SignalStatus,
        executed_price: Decimal | None = None,
        executed_quantity: int | None = None,
        order_id: int | None = None,
        order_no: str | None = None,
        exit_reason: str | None = None,
        realized_pnl: Decimal | None = None,
        realized_pnl_ratio: Decimal | None = None,
    ) -> StrategySignalModel | None:
        """시그널 실행 결과 업데이트"""
        signal = await self.get_by_id(signal_id)
        if not signal:
            return None

        signal.signal_status = status.value
        if executed_price is not None:
            signal.executed_price = executed_price
        if executed_quantity is not None:
            signal.executed_quantity = executed_quantity
        if order_id is not None:
            signal.order_id = order_id
        if order_no is not None:
            signal.order_no = order_no
        if exit_reason is not None:
            signal.exit_reason = exit_reason
        if realized_pnl is not None:
            signal.realized_pnl = realized_pnl
        if realized_pnl_ratio is not None:
            signal.realized_pnl_ratio = realized_pnl_ratio

        if status == SignalStatus.EXECUTED:
            signal.executed_at = datetime.now()

        await self.session.flush()
        await self.session.refresh(signal)
        return signal

    async def get_statistics(
        self, strategy_id: int, days: int | None = None
    ) -> dict:
        """시그널 통계 조회"""
        base_query = select(self.model).where(
            self.model.strategy_id == strategy_id
        )

        if days:
            since = datetime.now() - timedelta(days=days)
            base_query = base_query.where(self.model.signal_at >= since)

        # 전체 시그널 수
        total_stmt = select(func.count()).select_from(base_query.subquery())
        total_result = await self.session.execute(total_stmt)
        total_signals = total_result.scalar_one()

        # 매수 시그널 수
        buy_stmt = select(func.count()).select_from(
            base_query.where(self.model.signal_type == SignalType.BUY.value).subquery()
        )
        buy_result = await self.session.execute(buy_stmt)
        buy_signals = buy_result.scalar_one()

        # 매도 시그널 수
        sell_stmt = select(func.count()).select_from(
            base_query.where(self.model.signal_type == SignalType.SELL.value).subquery()
        )
        sell_result = await self.session.execute(sell_stmt)
        sell_signals = sell_result.scalar_one()

        # 체결된 시그널 수
        executed_stmt = select(func.count()).select_from(
            base_query.where(
                self.model.signal_status == SignalStatus.EXECUTED.value
            ).subquery()
        )
        executed_result = await self.session.execute(executed_stmt)
        executed_signals = executed_result.scalar_one()

        # 수익 거래 수
        profitable_stmt = select(func.count()).select_from(
            base_query.where(
                self.model.signal_status == SignalStatus.EXECUTED.value,
                self.model.realized_pnl > 0,
            ).subquery()
        )
        profitable_result = await self.session.execute(profitable_stmt)
        profitable_trades = profitable_result.scalar_one()

        # 총 실현 손익
        pnl_stmt = select(func.sum(self.model.realized_pnl)).select_from(
            base_query.where(
                self.model.signal_status == SignalStatus.EXECUTED.value
            ).subquery()
        )
        pnl_result = await self.session.execute(pnl_stmt)
        total_pnl = pnl_result.scalar_one() or Decimal("0")

        sell_executed = executed_signals // 2 if executed_signals > 0 else 0
        win_rate = (profitable_trades / sell_executed * 100) if sell_executed > 0 else 0

        return {
            "total_signals": total_signals,
            "buy_signals": buy_signals,
            "sell_signals": sell_signals,
            "executed_signals": executed_signals,
            "profitable_trades": profitable_trades,
            "total_pnl": float(total_pnl),
            "win_rate": win_rate,
        }
