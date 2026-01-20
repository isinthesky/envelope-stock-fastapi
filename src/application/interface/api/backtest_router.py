# -*- coding: utf-8 -*-
"""
Backtest Router - 백테스팅 API 엔드포인트
"""

from datetime import date, datetime, time

from fastapi import APIRouter, Depends, Query

from src.application.common.dependencies import DatabaseSession, get_kis_client, get_redis_client
from src.application.domain.backtest.dto import (
    BacktestRequestDTO,
    BacktestResultDTO,
    MultiSymbolBacktestRequestDTO,
    MultiSymbolBacktestResultDTO,
)
from src.application.domain.backtest.service import BacktestService
from src.application.domain.market_data.service import MarketDataService

router = APIRouter(prefix="/api/v1/backtest", tags=["Backtest"])


async def get_backtest_service(
    session: DatabaseSession,
    kis_client=Depends(get_kis_client),
    redis_client=Depends(get_redis_client)
) -> BacktestService:
    """백테스팅 서비스 의존성 (DB 세션 포함)"""
    market_data_service = MarketDataService(kis_client, redis_client)
    return BacktestService(market_data_service, db_session=session)


@router.post("/run", response_model=BacktestResultDTO)
async def run_backtest(
    request: BacktestRequestDTO,
    service: BacktestService = Depends(get_backtest_service)
):
    """
    백테스팅 실행

    단일 종목에 대한 백테스팅을 실행합니다.

    **Request Body:**
    - symbol: 종목코드 (예: "005930")
    - start_date: 시작일
    - end_date: 종료일
    - strategy_config: 전략 설정
    - backtest_config: 백테스팅 설정

    **Returns:**
    - BacktestResultDTO: 백테스팅 결과
    """
    result = await service.run_backtest(request)
    return result


@router.post("/run-multi", response_model=MultiSymbolBacktestResultDTO)
async def run_multi_symbol_backtest(
    request: MultiSymbolBacktestRequestDTO,
    service: BacktestService = Depends(get_backtest_service)
):
    """
    다중 종목 백테스팅

    여러 종목에 대한 백테스팅을 순차적으로 실행합니다.

    **Request Body:**
    - symbols: 종목코드 리스트 (예: ["005930", "000660"])
    - start_date: 시작일
    - end_date: 종료일
    - strategy_config: 전략 설정
    - backtest_config: 백테스팅 설정

    **Returns:**
    - MultiSymbolBacktestResultDTO: 종목별 백테스팅 결과
    """
    result = await service.run_multi_symbol_backtest(request)
    return result


@router.post("/validate-data")
async def validate_data_quality(
    symbol: str,
    start_date: date = Query(..., description="시작일 (YYYY-MM-DD)"),
    end_date: date = Query(..., description="종료일 (YYYY-MM-DD)"),
    service: BacktestService = Depends(get_backtest_service)
):
    """
    데이터 품질 검증

    백테스팅에 사용할 데이터의 품질을 검증합니다.

    **Query Parameters:**
    - symbol: 종목코드
    - start_date: 시작일 (YYYY-MM-DD)
    - end_date: 종료일 (YYYY-MM-DD)

    **Returns:**
    - dict: 데이터 품질 검증 결과
    """
    start_dt = datetime.combine(start_date, time.min)
    end_dt = datetime.combine(end_date, time.min)
    result = await service.validate_data_quality(symbol, start_dt, end_dt)
    return result


@router.get("/health")
async def health_check():
    """
    헬스체크

    백테스팅 서비스 상태를 확인합니다.
    """
    return {
        "status": "healthy",
        "service": "backtest",
        "version": "1.0.0"
    }
