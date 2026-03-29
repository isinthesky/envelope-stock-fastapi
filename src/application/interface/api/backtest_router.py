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
    UniverseBacktestRequestDTO,
    UniverseBacktestResultDTO,
)
from src.application.domain.backtest.service import BacktestService
from src.application.domain.market_data.service import MarketDataService
from src.application.domain.strategy.buy_strategy_service import BuyStrategyService
from src.application.domain.strategy.dto import StrategyConfigDTO

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


@router.post("/run-universe-golden-cross", response_model=UniverseBacktestResultDTO)
async def run_universe_golden_cross_backtest(
    request: UniverseBacktestRequestDTO,
    session: DatabaseSession,
    service: BacktestService = Depends(get_backtest_service),
):
    """종목 유니버스 기반 골든크로스 + 공격형 매도 백테스트 요약 실행"""
    strategy_params = {
        "short_period": 55,
        "long_period": 165,
        "stoch_k_period": 14,
        "stoch_d_period": 3,
        "stoch_oversold": 30.0,
        "stoch_overbought": 70.0,
        "require_k_above_d_for_buy": False,
        "require_k_below_d_for_sell": False,
    }
    if request.strategy_params:
        strategy_params.update(request.strategy_params)

    buy_service = BuyStrategyService(session=session)
    scan = await buy_service.scan_golden_cross_candidates(
        market=request.market,
        stoch_threshold=float(strategy_params.get("stoch_oversold", 30.0)),
        gc_only=False,
        include_etf=False,
        limit=max(request.limit * 5, request.limit),
    )

    preferred_states = ["OPTIMAL_BUY", "READY_TO_BUY", "BUY_INTEREST", "WAITING_FOR_PULLBACK"]
    selected_scan_items = [item for state in preferred_states for item in scan.stocks if item.gc_state == state]
    if request.eligible_only:
        selected_scan_items = [item for item in selected_scan_items if item.screening_score is not None]

    symbols = []
    seen_symbols = set()
    for item in selected_scan_items:
        if item.symbol in seen_symbols:
            continue
        seen_symbols.add(item.symbol)
        symbols.append(item.symbol)
        if len(symbols) >= request.limit:
            break
    if not symbols:
        return UniverseBacktestResultDTO(
            market=request.market,
            eligible_only=request.eligible_only,
            symbols=[],
            start_date=request.start_date,
            end_date=request.end_date,
            strategy_type=request.strategy_type,
            config_summary={
                "label": "공격형 중단기 스윙 매도 v1",
                "stop_loss": -0.05,
                "take_profit": 0.10,
                "trailing_stop": 0.07,
                "max_hold_days": 60,
            },
            summary=service.summarize_multi_symbol_results(
                MultiSymbolBacktestResultDTO(results={}, total_count=0, success_count=0, failed_count=0)
            ),
            results={},
        )

    strategy_config = StrategyConfigDTO()
    strategy_config.risk_management.use_stop_loss = True
    strategy_config.risk_management.stop_loss_ratio = -0.05
    strategy_config.risk_management.use_take_profit = True
    strategy_config.risk_management.take_profit_ratio = 0.10
    strategy_config.risk_management.use_trailing_stop = True
    strategy_config.risk_management.trailing_stop_ratio = 0.07
    strategy_config.risk_management.use_atr_stop_loss = False
    strategy_config.risk_management.use_atr_trailing_stop = False

    strategy_params = {
        "short_period": 55,
        "long_period": 165,
        "stoch_k_period": 14,
        "stoch_d_period": 3,
        "stoch_oversold": 30.0,
        "stoch_overbought": 70.0,
        "require_k_above_d_for_buy": False,
        "require_k_below_d_for_sell": False,
    }
    if request.strategy_params:
        strategy_params.update(request.strategy_params)

    multi_request = MultiSymbolBacktestRequestDTO(
        symbols=symbols,
        start_date=request.start_date,
        end_date=request.end_date,
        strategy_type=request.strategy_type,
        strategy_params=strategy_params,
        strategy_config=strategy_config,
        backtest_config=request.backtest_config,
    )
    multi_result = await service.run_multi_symbol_backtest(multi_request)

    config_summary = {
        "label": "공격형 중단기 스윙 매도 v1",
        "universe_count": len(symbols),
        "stop_loss": strategy_config.risk_management.stop_loss_ratio,
        "take_profit": strategy_config.risk_management.take_profit_ratio,
        "trailing_stop": strategy_config.risk_management.trailing_stop_ratio,
        "max_hold_days": 60,
        "entry_strategy": "golden_cross",
        "entry_params": strategy_params,
    }

    return service.build_universe_backtest_result(
        market=request.market,
        eligible_only=request.eligible_only,
        symbols=symbols,
        request=multi_request,
        multi_result=multi_result,
        config_summary=config_summary,
    )


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
