# -*- coding: utf-8 -*-
"""Personal flow snapshot repository"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.database.models.personal_flow_snapshot import PersonalFlowSnapshotModel
from src.adapters.database.repositories.base_repository import BaseRepository


class PersonalFlowSnapshotRepository(BaseRepository[PersonalFlowSnapshotModel]):
    def __init__(self, session: AsyncSession | None = None) -> None:
        super().__init__(PersonalFlowSnapshotModel, session)

    async def get_recent_by_symbol(
        self,
        symbol: str,
        limit: int = 5,
        session: AsyncSession | None = None,
    ) -> list[PersonalFlowSnapshotModel]:
        db = self._get_session(session)
        stmt = (
            select(self.model)
            .where(self.model.symbol == symbol)
            .order_by(self.model.biz_date.desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_latest_date_by_symbol(
        self,
        symbol: str,
        session: AsyncSession | None = None,
    ) -> str | None:
        db = self._get_session(session)
        stmt = select(func.max(self.model.biz_date)).where(self.model.symbol == symbol)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_symbol_between(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        session: AsyncSession | None = None,
    ) -> list[PersonalFlowSnapshotModel]:
        db = self._get_session(session)
        stmt = (
            select(self.model)
            .where(
                self.model.symbol == symbol,
                self.model.biz_date >= start_date,
                self.model.biz_date <= end_date,
            )
            .order_by(self.model.biz_date.asc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def count_by_symbol_between(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        session: AsyncSession | None = None,
    ) -> int:
        db = self._get_session(session)
        stmt = select(func.count()).select_from(self.model).where(
            self.model.symbol == symbol,
            self.model.biz_date >= start_date,
            self.model.biz_date <= end_date,
        )
        result = await db.execute(stmt)
        return int(result.scalar_one() or 0)

    async def upsert_snapshot(
        self,
        symbol: str,
        biz_date: str,
        individual_net_buy: int | None,
        close_price: int | None,
        trading_volume: int | None,
        source: str = "NAVER",
        session: AsyncSession | None = None,
    ) -> PersonalFlowSnapshotModel:
        db = self._get_session(session)
        stmt = select(self.model).where(
            self.model.source == source,
            self.model.symbol == symbol,
            self.model.biz_date == biz_date,
        )
        existing = (await db.execute(stmt)).scalar_one_or_none()
        if existing:
            existing.individual_net_buy = individual_net_buy
            existing.close_price = close_price
            existing.trading_volume = trading_volume
            await db.flush()
            return existing

        created = self.model(
            source=source,
            symbol=symbol,
            biz_date=biz_date,
            individual_net_buy=individual_net_buy,
            close_price=close_price,
            trading_volume=trading_volume,
        )
        db.add(created)
        await db.flush()
        return created
