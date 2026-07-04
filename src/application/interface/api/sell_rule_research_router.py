# -*- coding: utf-8 -*-
from fastapi import APIRouter, HTTPException, Query, status

from src.application.common.dependencies import AdminAccessDep, DatabaseSession
from src.application.common.dto import ResponseDTO
from src.application.domain.strategy.sell_rule_research_service import (
    SellPeakRuleResearchService,
)
from src.application.domain.strategy.sell_rule_preregistration_config import (
    SellRulePreRegistrationConfigError,
    build_preregistered_sell_rule_config,
)

router = APIRouter(prefix="/api/v1/strategies", tags=["Strategy"])


@router.get(
    "/sell-rules/preregistered/research",
    response_model=ResponseDTO[dict],
    status_code=status.HTTP_200_OK,
    summary="사전등록 매도 규칙 리서치",
    include_in_schema=False,
)
async def research_preregistered_sell_rules(
    admin_access: AdminAccessDep,
    session: DatabaseSession,
    symbols: str | None = Query(default=None, description="쉼표 구분 종목코드 목록"),
    start_date: str = Query(..., description="시작일 YYYYMMDD"),
    end_date: str = Query(..., description="종료일 YYYYMMDD"),
) -> ResponseDTO[dict]:
    _ = admin_access
    research_service = SellPeakRuleResearchService(session)
    try:
        config = build_preregistered_sell_rule_config(symbols, start_date, end_date)
    except SellRulePreRegistrationConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result = await research_service.research_preregistered_sell_rules(config)
    return ResponseDTO.success_response(result, "Preregistered sell rule research completed")
