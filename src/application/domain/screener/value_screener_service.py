# -*- coding: utf-8 -*-
"""
Value Stock Screener Service

가치주 스크리닝 서비스: 재무 지표 기반 종목 필터링
"""

import asyncio
import logging
from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.database.models.stock_universe import StockUniverseModel
from src.adapters.database.repositories.stock_universe_repository import (
    StockUniverseRepository,
)
from src.adapters.external.naver import NaverStockClient
from src.application.domain.screener.dto import (
    ValueScreenerCriteria,
    ValueScreenerResultDTO,
    ValueStockItemDTO,
)

logger = logging.getLogger(__name__)


class ValueScreenerService:
    """
    가치주 스크리닝 서비스

    네이버 금융 API를 통해 재무 데이터를 조회하고
    가치주 조건에 맞는 종목을 필터링합니다.
    """

    def __init__(
        self,
        naver_client: NaverStockClient,
        session: AsyncSession,
    ) -> None:
        self.naver_client = naver_client
        self.session = session
        self.repo = StockUniverseRepository(session)

    async def screen_stocks(
        self,
        criteria: ValueScreenerCriteria,
        symbols: list[str] | None = None,
        max_concurrent: int = 10,
    ) -> ValueScreenerResultDTO:
        """
        가치주 스크리닝 실행

        Args:
            criteria: 스크리닝 조건
            symbols: 스크리닝 대상 종목 목록 (None이면 stock_universe에서 조회)
            max_concurrent: 동시 API 호출 수 제한

        Returns:
            ValueScreenerResultDTO: 스크리닝 결과
        """
        # 1. 대상 종목 목록 조회
        if symbols:
            target_symbols = symbols
        else:
            stocks = await self._get_screeable_stocks()
            target_symbols = [stock.symbol for stock in stocks]

        total_count = len(target_symbols)
        logger.info(f"가치주 스크리닝 시작: {total_count}개 종목")

        # 2. 재무 데이터 조회 (병렬 처리, 동시 요청 수 제한)
        semaphore = asyncio.Semaphore(max_concurrent)

        async def fetch_with_limit(symbol: str):
            async with semaphore:
                return await self.naver_client.get_stock_financial_data(symbol)

        tasks = [fetch_with_limit(symbol) for symbol in target_symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 3. 필터링
        filtered_items: list[ValueStockItemDTO] = []

        for symbol, result in zip(target_symbols, results):
            if isinstance(result, Exception) or result is None:
                logger.debug(f"종목 {symbol} 데이터 조회 실패")
                continue

            # 조건 검사
            if not self._matches_criteria(result, criteria):
                continue

            # DTO 변환
            item = ValueStockItemDTO(
                symbol=result.symbol,
                name=result.name,
                market_cap=result.market_cap,
                market_cap_display=ValueStockItemDTO.format_market_cap(
                    result.market_cap
                ),
                retention_ratio=result.retention_ratio,
                quick_ratio=result.quick_ratio,
                debt_ratio=result.debt_ratio,
                roe=result.roe,
                per=result.per,
                pbr=result.pbr,
            )
            filtered_items.append(item)

        # 4. 정렬 (유보율 높은 순)
        filtered_items.sort(
            key=lambda x: (x.retention_ratio or 0, x.quick_ratio or 0),
            reverse=True,
        )

        logger.info(
            f"가치주 스크리닝 완료: {len(filtered_items)}/{total_count}개 종목 통과"
        )

        return ValueScreenerResultDTO(
            items=filtered_items,
            total_count=total_count,
            filtered_count=len(filtered_items),
            criteria=criteria,
        )

    async def get_stock_detail(self, symbol: str) -> ValueStockItemDTO | None:
        """
        개별 종목 재무 정보 조회

        Args:
            symbol: 종목코드

        Returns:
            ValueStockItemDTO 또는 None
        """
        result = await self.naver_client.get_stock_financial_data(symbol)

        if not result:
            return None

        return ValueStockItemDTO(
            symbol=result.symbol,
            name=result.name,
            market_cap=result.market_cap,
            market_cap_display=ValueStockItemDTO.format_market_cap(result.market_cap),
            retention_ratio=result.retention_ratio,
            quick_ratio=result.quick_ratio,
            debt_ratio=result.debt_ratio,
            roe=result.roe,
            per=result.per,
            pbr=result.pbr,
        )

    async def _get_screeable_stocks(self) -> Sequence[StockUniverseModel]:
        """스크리닝 대상 종목 조회"""
        return await self.repo.get_eligible_stocks(limit=500)

    def _matches_criteria(self, data, criteria: ValueScreenerCriteria) -> bool:
        """
        조건 일치 여부 확인

        Args:
            data: StockFinancialData
            criteria: 스크리닝 조건

        Returns:
            bool: 조건 만족 여부
        """
        # 1. 시가총액 검사
        if data.market_cap > criteria.max_market_cap:
            return False

        # 시가총액이 0인 경우 제외 (데이터 없음)
        if data.market_cap <= 0:
            return False

        # 2. 유보율 검사
        if criteria.min_retention_ratio > 0:
            if data.retention_ratio is None:
                return False
            if data.retention_ratio < criteria.min_retention_ratio:
                return False

        # 3. 당좌비율 검사
        if criteria.min_quick_ratio > 0:
            if data.quick_ratio is None:
                return False
            if data.quick_ratio < criteria.min_quick_ratio:
                return False

        # 4. 부채비율 검사 (상한)
        if criteria.max_debt_ratio is not None:
            if data.debt_ratio is None:
                return False
            if data.debt_ratio > criteria.max_debt_ratio:
                return False

        return True
