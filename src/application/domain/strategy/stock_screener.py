# -*- coding: utf-8 -*-
"""
Stock Screener - 종목 스크리너

시가총액, 거래량 기반 종목 필터링
"""

import logging
from datetime import datetime
from decimal import Decimal
from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.database.models.stock_universe import MarketType, StockUniverseModel
from src.adapters.database.repositories.stock_universe_repository import (
    StockUniverseRepository,
)
from src.adapters.external.kis_api.client import KISAPIClient
from src.application.domain.strategy.dto import StockScreenerConfigDTO

logger = logging.getLogger(__name__)


class StockScreener:
    """
    종목 스크리너

    시가총액, 거래량 등 조건에 따라 종목을 필터링합니다.
    """

    def __init__(
        self,
        session: AsyncSession,
        kis_client: KISAPIClient | None = None,
        config: StockScreenerConfigDTO | None = None,
    ):
        """
        Args:
            session: DB 세션
            kis_client: KIS API 클라이언트 (데이터 갱신용)
            config: 스크리너 설정
        """
        self.session = session
        self.kis_client = kis_client
        self.config = config or StockScreenerConfigDTO()
        self.repository = StockUniverseRepository(session)

    async def get_screening_candidates(
        self,
        market: MarketType | None = None,
    ) -> list[str]:
        """
        스크리닝 통과 종목 코드 목록 조회

        Args:
            market: 시장 구분 (None이면 전체)

        Returns:
            list[str]: 종목 코드 목록
        """
        stocks = await self.repository.get_eligible_stocks(
            market=market,
            limit=self.config.max_stocks,
        )
        return [stock.symbol for stock in stocks]

    async def get_eligible_stocks(
        self,
        market: MarketType | None = None,
    ) -> Sequence[StockUniverseModel]:
        """
        스크리닝 통과 종목 목록 조회

        Args:
            market: 시장 구분

        Returns:
            Sequence[StockUniverseModel]: 종목 목록
        """
        return await self.repository.get_eligible_stocks(
            market=market,
            limit=self.config.max_stocks,
        )

    async def apply_screening(self, symbol: str) -> bool:
        """
        개별 종목 스크리닝 적용

        Args:
            symbol: 종목코드

        Returns:
            bool: 스크리닝 통과 여부
        """
        stock = await self.repository.get_by_symbol(symbol)
        if not stock:
            return False

        # 시가총액 필터
        passed_market_cap = False
        if stock.market_cap:
            passed_market_cap = (
                self.config.min_market_cap
                <= float(stock.market_cap)
                <= self.config.max_market_cap
            )

        # 거래량 필터
        passed_volume = False
        if stock.avg_volume_20d:
            passed_volume = float(stock.avg_volume_20d) >= self.config.min_avg_volume

        # 가격대 필터
        passed_price_range = True
        if stock.current_price:
            passed_price_range = (
                self.config.min_price
                <= float(stock.current_price)
                <= self.config.max_price
            )

        # 섹터 제외
        if stock.sector and stock.sector in self.config.excluded_sectors:
            passed_market_cap = False

        # 스크리닝 점수 계산
        score = self._calculate_screening_score(stock)

        # 결과 저장
        await self.repository.update_screening_result(
            symbol=symbol,
            passed_market_cap=passed_market_cap,
            passed_volume=passed_volume,
            passed_price_range=passed_price_range,
            screening_score=score,
        )

        return passed_market_cap and passed_volume and passed_price_range

    def _calculate_screening_score(self, stock: StockUniverseModel) -> Decimal:
        """
        스크리닝 점수 계산

        점수 요소:
        - 시가총액 (적정 범위: 1000억 ~ 5조)
        - 거래량 (높을수록 좋음)
        - 52주 고점 대비 위치

        Args:
            stock: 종목 정보

        Returns:
            Decimal: 스크리닝 점수 (0~100)
        """
        score = Decimal("50")  # 기본 점수

        # 시가총액 점수 (1000억~5조 구간에서 최대 점수)
        if stock.market_cap:
            cap = float(stock.market_cap)
            if 100_000_000_000 <= cap <= 5_000_000_000_000:
                score += Decimal("20")
            elif cap < 100_000_000_000:
                score -= Decimal("10")
            else:  # 5조 초과
                score += Decimal("10")

        # 거래량 점수
        if stock.avg_volume_20d:
            vol = float(stock.avg_volume_20d)
            if vol >= 500_000:
                score += Decimal("15")
            elif vol >= 200_000:
                score += Decimal("10")
            elif vol >= 100_000:
                score += Decimal("5")

        # 52주 고점 대비 위치 (저점 매수 기회)
        if stock.from_52w_high_ratio:
            ratio = stock.from_52w_high_ratio
            if 0.6 <= ratio <= 0.8:  # 20~40% 하락
                score += Decimal("15")
            elif 0.8 <= ratio <= 0.9:  # 10~20% 하락
                score += Decimal("10")
            elif ratio > 0.95:  # 고점 부근
                score -= Decimal("10")

        return min(Decimal("100"), max(Decimal("0"), score))

    async def update_stock_data(
        self,
        symbol: str,
        name: str | None = None,
        market: str | None = None,
        sector: str | None = None,
        market_cap: Decimal | None = None,
        avg_volume_20d: Decimal | None = None,
        current_price: Decimal | None = None,
        **kwargs,
    ) -> StockUniverseModel:
        """
        종목 데이터 업데이트

        Args:
            symbol: 종목코드
            name: 종목명
            market: 시장 구분
            sector: 섹터
            market_cap: 시가총액
            avg_volume_20d: 20일 평균 거래량
            current_price: 현재가

        Returns:
            StockUniverseModel: 업데이트된 종목 정보
        """
        data = {
            k: v
            for k, v in {
                "name": name,
                "market": market,
                "sector": sector,
                "market_cap": market_cap,
                "avg_volume_20d": avg_volume_20d,
                "current_price": current_price,
                "is_active": True,
                "data_updated_at": datetime.now(),
                **kwargs,
            }.items()
            if v is not None
        }

        return await self.repository.upsert(symbol, **data)

    async def refresh_universe(
        self,
        stocks_data: list[dict],
    ) -> dict:
        """
        종목 유니버스 갱신

        Args:
            stocks_data: 종목 데이터 목록

        Returns:
            dict: 갱신 결과 통계
        """
        # 빈 데이터셋인 경우 비활성화하지 않고 스크리닝만 재적용
        if not stocks_data:
            logger.warning("[StockScreener] Empty stocks_data, skipping deactivation")
            screened = 0
            all_stocks = await self.repository.get_all()
            for stock in all_stocks:
                if stock.is_active:
                    passed = await self.apply_screening(stock.symbol)
                    if passed:
                        screened += 1

            await self.session.commit()

            return {
                "deactivated": 0,
                "updated": 0,
                "screened": screened,
                "refreshed_at": datetime.now().isoformat(),
                "warning": "Empty dataset - screening only applied to existing stocks",
            }

        # 기존 종목 비활성화 (데이터가 있는 경우에만)
        deactivated = await self.repository.deactivate_all()

        # 새 데이터 업데이트
        updated = 0
        for stock_data in stocks_data:
            symbol = stock_data.get("symbol")
            if not symbol:
                continue

            await self.update_stock_data(**stock_data)
            updated += 1

        # 스크리닝 적용
        screened = 0
        all_stocks = await self.repository.get_all()
        for stock in all_stocks:
            if stock.is_active:
                passed = await self.apply_screening(stock.symbol)
                if passed:
                    screened += 1

        await self.session.commit()

        return {
            "deactivated": deactivated,
            "updated": updated,
            "screened": screened,
            "refreshed_at": datetime.now().isoformat(),
        }

    async def exclude_symbol(self, symbol: str, reason: str) -> bool:
        """
        종목 제외

        Args:
            symbol: 종목코드
            reason: 제외 사유

        Returns:
            bool: 성공 여부
        """
        result = await self.repository.exclude_stock(symbol, reason)
        return result is not None

    async def include_symbol(self, symbol: str) -> bool:
        """
        제외된 종목 복원

        Args:
            symbol: 종목코드

        Returns:
            bool: 성공 여부
        """
        result = await self.repository.include_stock(symbol)
        return result is not None

    async def get_universe_statistics(self) -> dict:
        """
        유니버스 통계 조회

        Returns:
            dict: 통계 정보
        """
        return await self.repository.get_statistics()

    async def get_stocks_by_sector(
        self, sector: str
    ) -> Sequence[StockUniverseModel]:
        """
        섹터별 종목 조회

        Args:
            sector: 섹터

        Returns:
            Sequence[StockUniverseModel]: 종목 목록
        """
        return await self.repository.get_by_sector(sector)
