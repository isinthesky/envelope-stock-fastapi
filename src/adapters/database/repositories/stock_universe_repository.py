# -*- coding: utf-8 -*-
"""
Stock Universe Repository - 종목 유니버스 Repository

세션 계약 (2026-01-14 업데이트):
- 생성자에서 session은 Optional (하위 호환성 유지)
- 모든 메서드는 session을 파라미터로 받거나 생성자 session 사용
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

    def __init__(self, session: AsyncSession | None = None) -> None:
        super().__init__(StockUniverseModel, session)

    async def get_by_symbol(
        self,
        symbol: str,
        session: AsyncSession | None = None,
    ) -> StockUniverseModel | None:
        """종목코드로 조회"""
        return await self.get_one(session=session, symbol=symbol)

    async def get_eligible_stocks(
        self,
        market: MarketType | None = None,
        limit: int = 100,
        include_etf: bool = False,
        session: AsyncSession | None = None,
    ) -> Sequence[StockUniverseModel]:
        """
        스크리닝 통과한 종목 조회

        Args:
            market: 시장 필터 (KOSPI/KOSDAQ/ETF)
            limit: 최대 조회 개수
            include_etf: ETF 종목도 함께 조회 (market=None일 때만 적용)
            session: DB 세션 (없으면 생성자 세션 사용)
        """
        from sqlalchemy import or_

        db = self._get_session(session)

        # 기본 조건: 일반 주식
        base_condition = (
            (self.model.is_active == True) &
            (self.model.is_tradable == True) &
            (self.model.is_excluded == False) &
            (self.model.passed_market_cap == True) &
            (self.model.passed_volume == True)
        )

        # ETF 조건: 스크리닝 조건 완화 (활성화 + 거래 가능만 확인)
        etf_condition = (
            (self.model.is_active == True) &
            (self.model.is_tradable == True) &
            (self.model.is_excluded == False) &
            (self.model.market == MarketType.ETF.value)
        )

        if market:
            # 특정 시장 지정 시 해당 시장만
            stmt = select(self.model).where(
                base_condition if market != MarketType.ETF else etf_condition,
                self.model.market == market.value,
            )
        elif include_etf:
            # ETF 포함 옵션: 일반 주식 + ETF
            stmt = select(self.model).where(
                or_(base_condition, etf_condition)
            )
        else:
            # 기본: 일반 주식만
            stmt = select(self.model).where(base_condition)

        stmt = stmt.order_by(
            self.model.screening_score.desc().nullslast(),
            self.model.market_cap.desc().nullslast(),
        ).limit(limit)

        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_by_market_cap_range(
        self,
        min_cap: Decimal,
        max_cap: Decimal,
        min_volume: Decimal | None = None,
        session: AsyncSession | None = None,
    ) -> Sequence[StockUniverseModel]:
        """시가총액 범위로 종목 조회"""
        db = self._get_session(session)
        stmt = select(self.model).where(
            self.model.is_active == True,
            self.model.market_cap >= min_cap,
            self.model.market_cap <= max_cap,
        )

        if min_volume:
            stmt = stmt.where(self.model.avg_volume_20d >= min_volume)

        stmt = stmt.order_by(self.model.market_cap.desc())
        result = await db.execute(stmt)
        return result.scalars().all()

    async def upsert(
        self,
        symbol: str,
        session: AsyncSession | None = None,
        **kwargs,
    ) -> StockUniverseModel:
        """종목 Upsert"""
        db = self._get_session(session)
        existing = await self.get_by_symbol(symbol, session=db)

        if existing:
            for key, value in kwargs.items():
                setattr(existing, key, value)
            existing.data_updated_at = datetime.now()
            await db.flush()
            await db.refresh(existing)
            return existing
        else:
            return await self.create(session=db, symbol=symbol, **kwargs)

    async def bulk_upsert(
        self,
        stocks: list[dict],
        session: AsyncSession | None = None,
    ) -> int:
        """대량 Upsert"""
        db = self._get_session(session)
        count = 0
        for stock_data in stocks:
            symbol = stock_data.pop("symbol")
            await self.upsert(symbol, session=db, **stock_data)
            count += 1
        return count

    async def update_screening_result(
        self,
        symbol: str,
        passed_market_cap: bool,
        passed_volume: bool,
        passed_price_range: bool = True,
        screening_score: Decimal | None = None,
        session: AsyncSession | None = None,
    ) -> StockUniverseModel | None:
        """스크리닝 결과 업데이트"""
        db = self._get_session(session)
        stock = await self.get_by_symbol(symbol, session=db)
        if not stock:
            return None

        stock.passed_market_cap = passed_market_cap
        stock.passed_volume = passed_volume
        stock.passed_price_range = passed_price_range
        stock.screening_score = screening_score
        stock.screened_at = datetime.now()

        await db.flush()
        await db.refresh(stock)
        return stock

    async def exclude_stock(
        self,
        symbol: str,
        reason: str,
        session: AsyncSession | None = None,
    ) -> StockUniverseModel | None:
        """종목 제외"""
        db = self._get_session(session)
        stock = await self.get_by_symbol(symbol, session=db)
        if not stock:
            return None

        stock.is_excluded = True
        stock.exclude_reason = reason

        await db.flush()
        await db.refresh(stock)
        return stock

    async def include_stock(
        self,
        symbol: str,
        session: AsyncSession | None = None,
    ) -> StockUniverseModel | None:
        """제외된 종목 복원"""
        db = self._get_session(session)
        stock = await self.get_by_symbol(symbol, session=db)
        if not stock:
            return None

        stock.is_excluded = False
        stock.exclude_reason = None

        await db.flush()
        await db.refresh(stock)
        return stock

    async def get_by_sector(
        self,
        sector: str,
        limit: int = 100,
        session: AsyncSession | None = None,
    ) -> Sequence[StockUniverseModel]:
        """섹터별 종목 조회"""
        db = self._get_session(session)
        stmt = (
            select(self.model)
            .where(
                self.model.is_active == True,
                self.model.sector == sector,
            )
            .order_by(self.model.market_cap.desc().nullslast())
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_excluded_stocks(
        self,
        session: AsyncSession | None = None,
    ) -> Sequence[StockUniverseModel]:
        """제외된 종목 목록"""
        db = self._get_session(session)
        stmt = (
            select(self.model)
            .where(self.model.is_excluded == True)
            .order_by(self.model.symbol)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def deactivate_all(
        self,
        session: AsyncSession | None = None,
    ) -> int:
        """모든 종목 비활성화 (유니버스 갱신 전처리)"""
        db = self._get_session(session)
        stmt = update(self.model).values(is_active=False)
        result = await db.execute(stmt)
        return result.rowcount

    async def activate(
        self,
        symbol: str,
        session: AsyncSession | None = None,
    ) -> StockUniverseModel | None:
        """종목 활성화"""
        db = self._get_session(session)
        stock = await self.get_by_symbol(symbol, session=db)
        if not stock:
            return None

        stock.is_active = True
        await db.flush()
        await db.refresh(stock)
        return stock

    async def get_statistics(
        self,
        session: AsyncSession | None = None,
    ) -> dict:
        """유니버스 통계"""
        total = await self.count(session=session)
        active = await self.count(session=session, is_active=True)
        eligible = len(await self.get_eligible_stocks(limit=10000, session=session))
        excluded = await self.count(session=session, is_excluded=True)

        return {
            "total_stocks": total,
            "active_stocks": active,
            "eligible_stocks": eligible,
            "excluded_stocks": excluded,
        }
