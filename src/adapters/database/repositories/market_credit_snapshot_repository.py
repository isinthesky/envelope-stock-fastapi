# -*- coding: utf-8 -*-
"""Market credit snapshot repository"""

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.database.models.market_credit_snapshot import MarketCreditSnapshotModel
from src.adapters.database.repositories.base_repository import BaseRepository


class MarketCreditSnapshotRepository(BaseRepository[MarketCreditSnapshotModel]):
    def __init__(self, session: AsyncSession | None = None) -> None:
        super().__init__(MarketCreditSnapshotModel, session)

    async def get_recent_by_market(
        self,
        market_label: str,
        limit: int = 5,
        session: AsyncSession | None = None,
    ) -> list[MarketCreditSnapshotModel]:
        db = self._get_session(session)
        stmt = (
            select(self.model)
            .where(self.model.market_label == market_label)
            .order_by(self.model.biz_date.desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_latest_by_market(
        self,
        market_label: str,
        session: AsyncSession | None = None,
    ) -> MarketCreditSnapshotModel | None:
        rows = await self.get_recent_by_market(market_label=market_label, limit=1, session=session)
        return rows[0] if rows else None

    async def get_latest_date_by_market(
        self,
        market_label: str,
        session: AsyncSession | None = None,
    ) -> str | None:
        db = self._get_session(session)
        stmt = select(func.max(self.model.biz_date)).where(self.model.market_label == market_label)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_market_between(
        self,
        market_label: str,
        start_date: str,
        end_date: str,
        session: AsyncSession | None = None,
    ) -> list[MarketCreditSnapshotModel]:
        db = self._get_session(session)
        stmt = (
            select(self.model)
            .where(
                self.model.market_label == market_label,
                self.model.biz_date >= start_date,
                self.model.biz_date <= end_date,
            )
            .order_by(self.model.biz_date.asc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def count_by_market_between(
        self,
        market_label: str,
        start_date: str,
        end_date: str,
        session: AsyncSession | None = None,
    ) -> int:
        db = self._get_session(session)
        stmt = select(func.count()).select_from(self.model).where(
            self.model.market_label == market_label,
            self.model.biz_date >= start_date,
            self.model.biz_date <= end_date,
        )
        result = await db.execute(stmt)
        return int(result.scalar_one() or 0)

    async def delete_invalid_labels(
        self,
        valid_labels: list[str],
        session: AsyncSession | None = None,
    ) -> int:
        db = self._get_session(session)
        stmt = delete(self.model).where(~self.model.market_label.in_(valid_labels))
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount or 0

    async def upsert_snapshot(
        self,
        market_label: str,
        biz_date: str,
        trading_volume: int | None,
        balance_million: int | None,
        short_balance_million: int | None,
        source: str = "KOFIA",
        session: AsyncSession | None = None,
    ) -> MarketCreditSnapshotModel:
        db = self._get_session(session)
        stmt = select(self.model).where(
            self.model.source == source,
            self.model.market_label == market_label,
            self.model.biz_date == biz_date,
        )
        existing = (await db.execute(stmt)).scalar_one_or_none()
        if existing:
            existing.trading_volume = trading_volume
            existing.balance_million = balance_million
            existing.short_balance_million = short_balance_million
            await db.flush()
            return existing

        created = self.model(
            source=source,
            market_label=market_label,
            biz_date=biz_date,
            trading_volume=trading_volume,
            balance_million=balance_million,
            short_balance_million=short_balance_million,
        )
        db.add(created)
        await db.flush()
        return created
