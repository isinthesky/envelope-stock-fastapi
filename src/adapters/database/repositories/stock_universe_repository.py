# -*- coding: utf-8 -*-
"""
Stock Universe Repository - 종목 유니버스 Repository
"""

from datetime import datetime
from decimal import Decimal
from typing import Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.database.models.stock_universe import MarketType, StockUniverseModel
from src.adapters.database.repositories.base_repository import (
    BaseRepository,
    PaginationMixin,
)


class StockUniverseRepository(BaseRepository[StockUniverseModel], PaginationMixin):
    """종목 유니버스 Repository"""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(StockUniverseModel, session)

    async def get_by_symbol(self, symbol: str) -> StockUniverseModel | None:
        """종목코드로 조회"""
        return await self.get_one(symbol=symbol)

    async def get_eligible_stocks(
        self,
        market: MarketType | None = None,
        limit: int = 100,
    ) -> Sequence[StockUniverseModel]:
        """스크리닝 통과한 종목 조회"""
        stmt = select(self.model).where(
            self.model.is_active == True,
            self.model.is_tradable == True,
            self.model.is_excluded == False,
            self.model.passed_market_cap == True,
            self.model.passed_volume == True,
        )

        if market:
            stmt = stmt.where(self.model.market == market.value)

        stmt = stmt.order_by(
            self.model.screening_score.desc().nullslast(),
            self.model.market_cap.desc().nullslast(),
        ).limit(limit)

        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_by_market_cap_range(
        self,
        min_cap: Decimal,
        max_cap: Decimal,
        min_volume: Decimal | None = None,
    ) -> Sequence[StockUniverseModel]:
        """시가총액 범위로 종목 조회"""
        stmt = select(self.model).where(
            self.model.is_active == True,
            self.model.market_cap >= min_cap,
            self.model.market_cap <= max_cap,
        )

        if min_volume:
            stmt = stmt.where(self.model.avg_volume_20d >= min_volume)

        stmt = stmt.order_by(self.model.market_cap.desc())
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def upsert(self, symbol: str, **kwargs) -> StockUniverseModel:
        """종목 Upsert"""
        existing = await self.get_by_symbol(symbol)

        if existing:
            for key, value in kwargs.items():
                setattr(existing, key, value)
            existing.data_updated_at = datetime.now()
            await self.session.flush()
            await self.session.refresh(existing)
            return existing
        else:
            return await self.create(symbol=symbol, **kwargs)

    async def bulk_upsert(self, stocks: list[dict]) -> int:
        """대량 Upsert"""
        count = 0
        for stock_data in stocks:
            symbol = stock_data.pop("symbol")
            await self.upsert(symbol, **stock_data)
            count += 1
        return count

    async def update_screening_result(
        self,
        symbol: str,
        passed_market_cap: bool,
        passed_volume: bool,
        passed_price_range: bool = True,
        screening_score: Decimal | None = None,
    ) -> StockUniverseModel | None:
        """스크리닝 결과 업데이트"""
        stock = await self.get_by_symbol(symbol)
        if not stock:
            return None

        stock.passed_market_cap = passed_market_cap
        stock.passed_volume = passed_volume
        stock.passed_price_range = passed_price_range
        stock.screening_score = screening_score
        stock.screened_at = datetime.now()

        await self.session.flush()
        await self.session.refresh(stock)
        return stock

    async def exclude_stock(
        self, symbol: str, reason: str
    ) -> StockUniverseModel | None:
        """종목 제외"""
        stock = await self.get_by_symbol(symbol)
        if not stock:
            return None

        stock.is_excluded = True
        stock.exclude_reason = reason

        await self.session.flush()
        await self.session.refresh(stock)
        return stock

    async def include_stock(self, symbol: str) -> StockUniverseModel | None:
        """제외된 종목 복원"""
        stock = await self.get_by_symbol(symbol)
        if not stock:
            return None

        stock.is_excluded = False
        stock.exclude_reason = None

        await self.session.flush()
        await self.session.refresh(stock)
        return stock

    async def get_by_sector(
        self, sector: str, limit: int = 100
    ) -> Sequence[StockUniverseModel]:
        """섹터별 종목 조회"""
        stmt = (
            select(self.model)
            .where(
                self.model.is_active == True,
                self.model.sector == sector,
            )
            .order_by(self.model.market_cap.desc().nullslast())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_excluded_stocks(self) -> Sequence[StockUniverseModel]:
        """제외된 종목 목록"""
        stmt = (
            select(self.model)
            .where(self.model.is_excluded == True)
            .order_by(self.model.symbol)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def deactivate_all(self) -> int:
        """모든 종목 비활성화 (유니버스 갱신 전처리)"""
        stmt = update(self.model).values(is_active=False)
        result = await self.session.execute(stmt)
        return result.rowcount

    async def activate(self, symbol: str) -> StockUniverseModel | None:
        """종목 활성화"""
        stock = await self.get_by_symbol(symbol)
        if not stock:
            return None

        stock.is_active = True
        await self.session.flush()
        await self.session.refresh(stock)
        return stock

    async def get_statistics(self) -> dict:
        """유니버스 통계"""
        total = await self.count()
        active = await self.count(is_active=True)
        eligible = len(await self.get_eligible_stocks(limit=10000))
        excluded = await self.count(is_excluded=True)

        return {
            "total_stocks": total,
            "active_stocks": active,
            "eligible_stocks": eligible,
            "excluded_stocks": excluded,
        }
