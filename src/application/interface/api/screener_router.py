# -*- coding: utf-8 -*-
"""
Screener Router - 종목 스크리닝 API 엔드포인트
"""

from fastapi import APIRouter, Body, Query, status

from src.adapters.external.naver import get_naver_stock_client
from src.application.common.dependencies import AdminAccessDep, DatabaseSession
from src.application.common.dto import ResponseDTO
from src.application.domain.screener.dto import (
    ValueScreenerCriteria,
    ValueScreenerResultDTO,
    ValueStockItemDTO,
)
from src.application.domain.screener.value_screener_service import ValueScreenerService

router = APIRouter(prefix="/api/v1/screener", tags=["Screener"])


@router.post(
    "/value-stocks",
    response_model=ResponseDTO[ValueScreenerResultDTO],
    status_code=status.HTTP_200_OK,
    summary="가치주 스크리닝",
    description="재무 지표 기반 가치주 스크리닝 실행",
)
async def screen_value_stocks(
    session: DatabaseSession,
    criteria: ValueScreenerCriteria = Body(default_factory=ValueScreenerCriteria),
    symbols: list[str] | None = Body(default=None, description="대상 종목 목록 (없으면 전체)"),
    admin_access: AdminAccessDep = None,
) -> ResponseDTO[ValueScreenerResultDTO]:
    """가치주 스크리닝"""
    _ = admin_access
    naver_client = get_naver_stock_client()
    service = ValueScreenerService(naver_client, session)

    result = await service.screen_stocks(criteria, symbols)
    return ResponseDTO.success_response(result, "가치주 스크리닝 완료")


@router.get(
    "/stock/{symbol}/financial",
    response_model=ResponseDTO[ValueStockItemDTO],
    status_code=status.HTTP_200_OK,
    summary="종목 재무 정보 조회",
    description="개별 종목의 재무 정보 조회 (네이버 금융)",
)
async def get_stock_financial(
    symbol: str,
    session: DatabaseSession,
) -> ResponseDTO[ValueStockItemDTO]:
    """개별 종목 재무 정보 조회"""
    naver_client = get_naver_stock_client()
    service = ValueScreenerService(naver_client, session)

    result = await service.get_stock_detail(symbol)

    if not result:
        return ResponseDTO.error_response(f"종목 {symbol} 정보를 찾을 수 없습니다")

    return ResponseDTO.success_response(result, "종목 재무 정보 조회 완료")


@router.get(
    "/presets",
    response_model=ResponseDTO[dict],
    status_code=status.HTTP_200_OK,
    summary="스크리닝 프리셋 목록",
    description="미리 정의된 스크리닝 조건 프리셋",
)
async def get_screener_presets() -> ResponseDTO[dict]:
    """스크리닝 프리셋 목록"""
    presets = {
        "small_cap_value": {
            "name": "소형 가치주",
            "description": "시가총액 5000억 미만, 유보율 500% 이상",
            "criteria": {
                "max_market_cap": 500_000_000_000,
                "min_retention_ratio": 500,
                "min_quick_ratio": 0,
                "max_debt_ratio": None,
            },
        },
        "cash_rich": {
            "name": "현금 부자",
            "description": "당좌비율 200% 이상, 부채비율 50% 미만",
            "criteria": {
                "max_market_cap": 1_000_000_000_000,
                "min_retention_ratio": 0,
                "min_quick_ratio": 200,
                "max_debt_ratio": 50,
            },
        },
        "low_debt_value": {
            "name": "저부채 가치주",
            "description": "부채비율 30% 미만, 유보율 1000% 이상",
            "criteria": {
                "max_market_cap": 1_000_000_000_000,
                "min_retention_ratio": 1000,
                "min_quick_ratio": 100,
                "max_debt_ratio": 30,
            },
        },
    }
    return ResponseDTO.success_response(presets, "스크리닝 프리셋 목록")
