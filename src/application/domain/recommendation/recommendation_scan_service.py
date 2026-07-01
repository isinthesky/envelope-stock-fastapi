# -*- coding: utf-8 -*-
"""
Recommendation Scan Service

가치주 스크리너(ValueScreenerService) + 골든크로스 스캔(BuyStrategyService) 결과를
종목 코드 기준으로 병합해 추천 후보(RecommendationCandidateDTO) 목록을 만든다.

두 서비스의 기존 public 메서드 시그니처/반환 계약은 변경하지 않는다(읽기 전용 합성).
"""

import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.external.naver import NaverStockClient
from src.application.domain.recommendation.dto import (
    RecommendationCandidateDTO,
    RecommendationCandidateListDTO,
)
from src.application.domain.recommendation.readiness_rules import (
    compute_scorecard,
    determine_readiness,
)
from src.application.domain.screener.dto import ValueScreenerCriteria, ValueStockItemDTO
from src.application.domain.screener.value_screener_service import ValueScreenerService
from src.application.domain.strategy.buy_strategy_service import BuyStrategyService
from src.application.domain.strategy.dto import GoldenCrossScanItemDTO

logger = logging.getLogger(__name__)


class RecommendationScanService:
    """
    추천 후보 스캔 서비스

    골든크로스 스캔 결과를 기준 목록으로 삼고, 가치주 스크리너 결과를
    심볼 기준으로 붙여 재무 근거 유무를 판단한다.
    """

    def __init__(
        self,
        naver_client: NaverStockClient,
        session: AsyncSession,
    ) -> None:
        self.naver_client = naver_client
        self.session = session

    async def scan_candidates(
        self,
        market: str | None = None,
        stoch_threshold: float = 30.0,
        gc_only: bool = True,
        include_etf: bool = True,
        limit: int = 1000,
        max_concurrent: int | None = None,
        value_criteria: ValueScreenerCriteria | None = None,
    ) -> RecommendationCandidateListDTO:
        """
        골든크로스 스캔 결과와 가치주 스크리너 결과를 병합해 추천 후보를 생성한다.

        Args:
            market: 시장 필터 (KOSPI/KOSDAQ/ETF)
            stoch_threshold: Stochastic 과매도 임계값
            gc_only: 골든크로스 활성 종목만 스캔 대상으로 포함
            include_etf: ETF 종목 포함 여부
            limit: 스캔 대상 최대 종목 수
            max_concurrent: 골든크로스 스캔 동시 처리 수
            value_criteria: 가치주 스크리닝 조건 (미지정 시 기본값)

        Returns:
            RecommendationCandidateListDTO: 추천 후보 목록
        """
        buy_service = BuyStrategyService(session=self.session)
        # session을 첫 positional 인자로 전달해 @transaction이 새 세션을 여는 대신
        # 이 서비스에 주입된 요청 세션을 재사용하게 한다.
        gc_result = await buy_service.scan_golden_cross_candidates(
            self.session,
            market=market,
            stoch_threshold=stoch_threshold,
            gc_only=gc_only,
            include_etf=include_etf,
            limit=limit,
            max_concurrent=max_concurrent,
        )

        value_by_symbol: dict[str, ValueStockItemDTO] = {}
        if gc_result.stocks:
            value_service = ValueScreenerService(self.naver_client, self.session)
            value_result = await value_service.screen_stocks(
                value_criteria or ValueScreenerCriteria(),
                symbols=[stock.symbol for stock in gc_result.stocks],
            )
            value_by_symbol = {item.symbol: item for item in value_result.items}

        candidates = [
            self._build_candidate(gc_item, value_by_symbol.get(gc_item.symbol))
            for gc_item in gc_result.stocks
        ]

        logger.info(
            f"[Recommendation Scan] Complete: {len(candidates)} candidates "
            f"(fundamental evidence: {sum(1 for c in candidates if c.has_fundamental_evidence)})"
        )

        return RecommendationCandidateListDTO(
            candidates=candidates,
            total_scanned=gc_result.total_scanned,
            candidate_count=len(candidates),
            generated_at=datetime.now(),
            errors=gc_result.errors,
        )

    @staticmethod
    def _build_candidate(
        gc_item: GoldenCrossScanItemDTO, value_item: ValueStockItemDTO | None
    ) -> RecommendationCandidateDTO:
        has_fundamental_evidence = value_item is not None
        scorecard = compute_scorecard(gc_item.gc_state, has_fundamental_evidence)
        readiness_label, missing_evidence, blocked_actions = determine_readiness(
            gc_item.gc_state, has_fundamental_evidence
        )

        return RecommendationCandidateDTO(
            symbol=gc_item.symbol,
            name=gc_item.name,
            market=gc_item.market,
            current_price=gc_item.current_price,
            technical_state=gc_item.gc_state,
            has_fundamental_evidence=has_fundamental_evidence,
            scorecard=scorecard,
            readiness_label=readiness_label,
            missing_evidence=missing_evidence,
            blocked_actions=blocked_actions,
        )
