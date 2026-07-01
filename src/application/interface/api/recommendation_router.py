# -*- coding: utf-8 -*-
"""
Recommendation Router - 추천 후보 API 엔드포인트
"""

from fastapi import APIRouter, Depends, Query, status

from src.adapters.external.naver import get_naver_stock_client
from src.application.common.dependencies import AdminAccessDep, DatabaseSession
from src.application.common.dto import ResponseDTO
from src.application.domain.backtest.service import BacktestService
from src.application.domain.recommendation.dto import (
    RecommendationCandidateListDTO,
    RecommendationRuleSetCreateRequestDTO,
    RecommendationRuleSetDTO,
    RecommendationRuleSetListDTO,
    RecommendationRuleSetValidationRequestDTO,
    RecommendationRuleSetValidationResultDTO,
)
from src.application.domain.recommendation.recommendation_scan_service import (
    RecommendationScanService,
)
from src.application.domain.recommendation.rule_set_service import RecommendationRuleSetService
from src.application.interface.api.backtest_router import get_backtest_service

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
    rule_set_id: str | None = Query(
        default=None, description="지정 시 저장된 active 룰셋의 검증된 파라미터를 사용"
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
        rule_set_id=rule_set_id,
    )
    return ResponseDTO.success_response(result, "추천 후보 조회 완료")


@router.post(
    "/rule-sets",
    response_model=ResponseDTO[RecommendationRuleSetDTO],
    status_code=status.HTTP_201_CREATED,
    summary="추천 검색식 룰셋 등록",
    description="후보(candidate) 목록을 draft 상태 룰셋으로 등록한다. validate 성공 시 active로 전환된다.",
)
async def create_recommendation_rule_set(
    request: RecommendationRuleSetCreateRequestDTO,
    admin_access: AdminAccessDep = None,
) -> ResponseDTO[RecommendationRuleSetDTO]:
    _ = admin_access
    service = RecommendationRuleSetService()
    rule_set = await service.create_rule_set(request)
    return ResponseDTO.success_response(rule_set, "룰셋 등록 완료")


@router.get(
    "/rule-sets",
    response_model=ResponseDTO[RecommendationRuleSetListDTO],
    status_code=status.HTTP_200_OK,
    summary="추천 검색식 룰셋 목록 조회",
)
async def list_recommendation_rule_sets(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    admin_access: AdminAccessDep = None,
) -> ResponseDTO[RecommendationRuleSetListDTO]:
    _ = admin_access
    service = RecommendationRuleSetService()
    result = await service.list_rule_sets(limit=limit, offset=offset)
    return ResponseDTO.success_response(result, "룰셋 목록 조회 완료")


@router.post(
    "/rule-sets/{rule_id}/validate",
    response_model=ResponseDTO[RecommendationRuleSetValidationResultDTO],
    status_code=status.HTTP_200_OK,
    summary="추천 검색식 룰셋 walk-forward 검증",
    description=(
        "룰셋 후보들을 train/test 기간으로 나눠 백테스트한다. 후보 선정은 selection_metric "
        "기준 train(학습) 지표로 이뤄지며, test(OOS) 지표는 선정에 관여하지 않고 그 선택이 "
        "과최적화되지 않았는지 검증하는 용도로만 함께 기록된다(표준 walk-forward 방법론). "
        "후보 수 x 2(train/test) 만큼 백테스트가 실행되므로 비용이 크다. "
        "검증 성공 시 룰셋 상태가 active로 바뀌고 선정 후보의 frozen_hash가 기록된다."
    ),
)
async def validate_recommendation_rule_set(
    rule_id: str,
    request: RecommendationRuleSetValidationRequestDTO,
    backtest_service: BacktestService = Depends(get_backtest_service),
    admin_access: AdminAccessDep = None,
) -> ResponseDTO[RecommendationRuleSetValidationResultDTO]:
    _ = admin_access
    service = RecommendationRuleSetService()
    result = await service.validate_rule_set(rule_id, request, backtest_service)
    return ResponseDTO.success_response(result, "룰셋 검증 완료")
