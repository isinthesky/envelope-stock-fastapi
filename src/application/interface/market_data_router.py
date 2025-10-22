# -*- coding: utf-8 -*-
"""
MarketData Router - 시세 데이터 API 엔드포인트
"""

from fastapi import APIRouter, Query, status

from src.application.common.dependencies import KISClientDep, RedisDep
from src.application.common.dto import ResponseDTO
from src.application.domain.market_data.dto import (
    ChartResponseDTO,
    OrderbookResponseDTO,
    PriceResponseDTO,
)
from src.application.domain.market_data.service import MarketDataService

router = APIRouter()


@router.get(
    "/price/{symbol}",
    response_model=ResponseDTO[PriceResponseDTO],
    status_code=status.HTTP_200_OK,
    summary="현재가 조회",
    description="종목의 현재가 정보 조회 (캐시 5초)",
)
async def get_current_price(
    symbol: str,
    use_cache: bool = Query(default=True, description="캐시 사용 여부"),
    kis_client: KISClientDep = None,
    redis: RedisDep = None,
) -> ResponseDTO[PriceResponseDTO]:
    """현재가 조회"""
    service = MarketDataService(kis_client, redis)
    price_data = await service.get_current_price(symbol, use_cache=use_cache)
    return ResponseDTO.success_response(price_data, "Current price retrieved successfully")


@router.get(
    "/orderbook/{symbol}",
    response_model=ResponseDTO[OrderbookResponseDTO],
    status_code=status.HTTP_200_OK,
    summary="호가 조회",
    description="종목의 10단계 호가 정보 조회 (캐시 5초)",
)
async def get_orderbook(
    symbol: str,
    use_cache: bool = Query(default=True, description="캐시 사용 여부"),
    kis_client: KISClientDep = None,
    redis: RedisDep = None,
) -> ResponseDTO[OrderbookResponseDTO]:
    """호가 조회"""
    service = MarketDataService(kis_client, redis)
    orderbook_data = await service.get_orderbook(symbol, use_cache=use_cache)
    return ResponseDTO.success_response(orderbook_data, "Orderbook retrieved successfully")


@router.get(
    "/chart/{symbol}",
    response_model=ResponseDTO[ChartResponseDTO],
    status_code=status.HTTP_200_OK,
    summary="차트 데이터 조회",
    description="종목의 차트 데이터 조회 (일봉/주봉/월봉)",
)
async def get_chart_data(
    symbol: str,
    interval: str = Query(default="1d", description="시간 간격 (1d, 1h 등)"),
    kis_client: KISClientDep = None,
    redis: RedisDep = None,
) -> ResponseDTO[ChartResponseDTO]:
    """차트 데이터 조회"""
    service = MarketDataService(kis_client, redis)
    chart_data = await service.get_chart_data(symbol, interval=interval)
    return ResponseDTO.success_response(chart_data, "Chart data retrieved successfully")
