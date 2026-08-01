# -*- coding: utf-8 -*-
"""
Sell risk data backfill service

시장 신용(KOFIA)과 개인 수급(Naver) 캐시를 DB에 백필한다.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.database.models.stock_universe import StockUniverseModel
from src.adapters.database.repositories.analysis_history_repository import (
    AnalysisHistoryRepository,
)
from src.application.domain.strategy.symbol_validation import (
    filter_tradable_items,
    split_valid_symbols,
)
from src.adapters.external.kofia_client import get_kofia_client
from src.adapters.external.naver.stock_client import get_naver_stock_client

logger = logging.getLogger(__name__)


class SellRiskBackfillService:
    """매도 리스크 오버레이 데이터 백필 서비스"""

    def __init__(self, session: AsyncSession | None = None) -> None:
        self.session = session

    async def resolve_symbols(self, symbols: list[str] | None = None) -> list[dict[str, str | None]]:
        if symbols:
            # 명시적 입력도 형식 검증을 통과한 종목만 사용 (메모 행 등 우회 차단)
            valid_symbols, skipped = split_valid_symbols(symbols)
            if skipped:
                logger.warning(
                    "[SellRiskBackfill] Skipping invalid symbols: %s", skipped
                )
            if not valid_symbols:
                return []
            return await self._resolve_symbol_metadata(valid_symbols)

        if self.session is None:
            return []

        rows = await AnalysisHistoryRepository(self.session).get_active_symbols_with_names(
            "sell",
            session=self.session,
        )
        rows, _skipped = filter_tradable_items(rows)
        return rows

    async def _resolve_symbol_metadata(
        self,
        symbols: list[str],
    ) -> list[dict[str, str | None]]:
        if self.session is None:
            return [{"symbol": symbol, "name": None, "market": None} for symbol in symbols]

        stmt = select(
            StockUniverseModel.symbol,
            StockUniverseModel.name,
            StockUniverseModel.market,
        )
        if symbols:
            stmt = stmt.where(StockUniverseModel.symbol.in_(symbols))

        result = await self.session.execute(stmt)
        rows = [
            {"symbol": row[0], "name": row[1], "market": row[2]}
            for row in result.all()
        ]

        if symbols:
            mapped = {row["symbol"]: row for row in rows}
            return [
                mapped.get(symbol, {"symbol": symbol, "name": None, "market": None})
                for symbol in symbols
            ]
        return rows

    async def backfill_market_credit(
        self,
        years: int = 2,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        return await get_kofia_client().backfill_market_credit_cache(
            years=years,
            end_date=end_date,
        )

    async def backfill_personal_flow(
        self,
        symbols: list[str] | None = None,
        years: int = 2,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        resolved_symbols = await self.resolve_symbols(symbols)
        client = get_naver_stock_client()
        results: list[dict[str, Any]] = []

        for row in resolved_symbols:
            symbol = row["symbol"]
            if not symbol:
                continue
            result = await client.backfill_personal_flow_cache(
                symbol=symbol,
                years=years,
                end_date=end_date,
            )
            results.append(result)

        return {
            "years": years,
            "end_date": end_date or date.today().strftime("%Y%m%d"),
            "symbol_count": len(results),
            "results": results,
        }

    async def backfill_all(
        self,
        symbols: list[str] | None = None,
        years: int = 2,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        return {
            "market_credit": await self.backfill_market_credit(years=years, end_date=end_date),
            "personal_flow": await self.backfill_personal_flow(
                symbols=symbols,
                years=years,
                end_date=end_date,
            ),
        }

