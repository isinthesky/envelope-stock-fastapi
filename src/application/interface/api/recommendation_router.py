# -*- coding: utf-8 -*-
"""
Recommendation Router - 추천 후보 API 엔드포인트
"""

from fastapi import APIRouter, Query, status

from src.adapters.external.naver import get_naver_stock_client
from src.application.common.dependencies import AdminAccessDep, DatabaseSession
from src.application.common.dto import ResponseDTO
from src.application.domain.recommendation.dto import RecommendationCandidateListDTO
from src.application.domain.recommendation.recommendation_scan_service import (
    RecommendationScanService,
)

router = APIRouter(prefix="/api/v1/recommendations", tags=["Recommendation"])


@router.get(
    "/candidates",
    response_model=ResponseDTO[RecommendationCandidateListDTO],
    status_code=status.HTTP_200_OK,
    summary="추천 후보 목록",
    description=(
        "가치주 스크리너와 골든크로스 스캔 결과를 병합해 readiness_label/"
        "missing_evidence/blocked_actions가 부여된 추천 후보 목록을 반환한다. "
        "AI 분석과 실주문은 관여하지 않는다(Phase 1). "
        "가치주 스크리너(재무 데이터) 조회를 포함하므로 관리자 IP 허용 목록에서만 호출 가능하다."
    ),
)
async def get_recommendation_candidates(
    session: DatabaseSession,
    market: str | None = Query(default=None, description="시장 구분 (KOSPI/KOSDAQ/ETF)"),
    stoch_threshold: float = Query(
        default=30.0, ge=10.0, le=50.0, description="Stochastic 과매도 임계값"
    ),
    gc_only: bool = Query(default=True, description="골든크로스 활성 종목만 스캔 대상 포함"),
    include_etf: bool = Query(default=True, description="ETF 종목 포함 여부"),
    limit: int = Query(default=1000, ge=1, le=5000, description="스캔 대상 최대 종목 수"),
    max_concurrent: int | None = Query(
        default=None, ge=1, le=50, description="골든크로스 스캔 동시 처리 수"
    ),
    admin_access: AdminAccessDep = None,
) -> ResponseDTO[RecommendationCandidateListDTO]:
    """추천 후보 조회 - 가치주 스크리너(POST /screener/value-stocks)와 동일하게 관리자 IP만 허용."""
    _ = admin_access
    naver_client = get_naver_stock_client()
    service = RecommendationScanService(naver_client, session)

    result = await service.scan_candidates(
        market=market,
        stoch_threshold=stoch_threshold,
        gc_only=gc_only,
        include_etf=include_etf,
        limit=limit,
        max_concurrent=max_concurrent,
    )
    return ResponseDTO.success_response(result, "추천 후보 조회 완료")
