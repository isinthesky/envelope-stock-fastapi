# -*- coding: utf-8 -*-
"""
Strategy Router - 전략 관리 API 엔드포인트

NOTE: 라우터 순서 중요!
- 정적 경로 (/universe, /scheduler/status)를 동적 경로 (/{strategy_id}) 앞에 정의
- FastAPI는 순서대로 경로를 매칭하므로 동적 경로가 먼저 오면 정적 경로가 무시됨
"""

from fastapi import APIRouter, HTTPException, Query, status

from src.application.common.dependencies import DatabaseSession, MarketDataServiceDep
from src.application.common.dto import ResponseDTO
from src.application.domain.strategy.dto import (
    AnalysisHistoryCreateDTO,
    AnalysisHistoryDTO,
    AnalysisHistoryListDTO,
    AnalysisHistoryRefreshResultDTO,
    GoldenCrossConfigDTO,
    GoldenCrossScanListDTO,
    SellSignalAnalysisDTO,
    SignalListDTO,
    SignalStatisticsDTO,
    StockUniverseListDTO,
    StrategyCreateRequestDTO,
    StrategyDetailResponseDTO,
    StrategyExecuteRequestDTO,
    StrategyExecuteResultDTO,
    StrategyListResponseDTO,
    StrategyUpdateRequestDTO,
    SymbolStateListDTO,
)
from src.application.domain.strategy.strategy_service import StrategyService

router = APIRouter()


# ==================== 정적 경로 (동적 경로보다 먼저 정의) ====================


@router.post(
    "",
    response_model=ResponseDTO[StrategyDetailResponseDTO],
    status_code=status.HTTP_201_CREATED,
    summary="전략 생성",
    description="새로운 자동매매 전략 생성",
)
async def create_strategy(
    request: StrategyCreateRequestDTO,
) -> ResponseDTO[StrategyDetailResponseDTO]:
    """전략 생성 - @transaction이 세션을 관리"""
    service = StrategyService()
    strategy_data = await service.create_strategy(request)
    return ResponseDTO.success_response(strategy_data, "Strategy created successfully")


@router.get(
    "",
    response_model=ResponseDTO[StrategyListResponseDTO],
    status_code=status.HTTP_200_OK,
    summary="전략 목록 조회",
    description="계좌별 전략 목록 조회",
)
async def get_strategy_list(
    account_no: str | None = None,
    status_filter: str | None = None,
    session: DatabaseSession = None,
) -> ResponseDTO[StrategyListResponseDTO]:
    """전략 목록 조회"""
    service = StrategyService(session)
    strategy_list = await service.get_strategy_list(account_no, status_filter)
    return ResponseDTO.success_response(strategy_list, "Strategy list retrieved successfully")


# ==================== Universe Endpoints (정적 경로) ====================


@router.get(
    "/universe",
    response_model=ResponseDTO[StockUniverseListDTO],
    status_code=status.HTTP_200_OK,
    summary="종목 유니버스 조회",
    description="스크리닝 통과 종목 목록 조회",
)
async def get_universe(
    session: DatabaseSession,
    market: str | None = Query(default=None, description="시장 구분 (KOSPI/KOSDAQ)"),
    eligible_only: bool = Query(default=True, description="스크리닝 통과 종목만"),
) -> ResponseDTO[StockUniverseListDTO]:
    """종목 유니버스 조회"""
    service = StrategyService(session)
    universe = await service.get_stock_universe(market, eligible_only)
    return ResponseDTO.success_response(universe, "Universe retrieved successfully")


@router.post(
    "/universe/refresh",
    response_model=ResponseDTO[dict],
    status_code=status.HTTP_200_OK,
    summary="유니버스 갱신",
    description="종목 유니버스 데이터 갱신",
)
async def refresh_universe(
    session: DatabaseSession,
    market_data_service: MarketDataServiceDep,
) -> ResponseDTO[dict]:
    """유니버스 갱신"""
    if not market_data_service.has_valid_credentials():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="KIS API credentials not configured",
        )

    service = StrategyService(session)
    result = await service.refresh_universe()
    return ResponseDTO.success_response(result, "Universe refresh completed")


@router.get(
    "/universe/golden-cross-scan",
    response_model=ResponseDTO[GoldenCrossScanListDTO],
    status_code=status.HTTP_200_OK,
    summary="골든크로스 종목 스캔",
    description="유니버스 종목에 대해 기술적 지표를 계산하고 골든크로스 조건에 부합하는 종목 필터링",
)
async def scan_golden_cross(
    session: DatabaseSession,
    market: str | None = Query(default=None, description="시장 구분 (KOSPI/KOSDAQ)"),
    stoch_threshold: float = Query(default=30.0, ge=10.0, le=50.0, description="Stochastic 과매도 임계값"),
    gc_only: bool = Query(default=True, description="골든크로스 활성 종목만 반환"),
) -> ResponseDTO[GoldenCrossScanListDTO]:
    """
    골든크로스 종목 스캔

    스크리닝 통과 종목에 대해 MA40, MA160, Stochastic K/D 지표를 계산하고
    골든크로스 전략 조건에 따라 종목을 필터링합니다.

    상태:
    - READY_TO_BUY: 골든크로스 활성 + Stochastic 과매도 (매수 적기)
    - WAITING_FOR_PULLBACK: 골든크로스 활성 + Stochastic 중간 (눌림목 대기)
    - GC_ACTIVE: 골든크로스 활성 + Stochastic 과매수 (대기)
    - NOT_GC: 골든크로스 비활성 (MA40 < MA160)
    """
    service = StrategyService(session)
    result = await service.scan_golden_cross_candidates(
        market=market,
        stoch_threshold=stoch_threshold,
        gc_only=gc_only,
    )
    return ResponseDTO.success_response(result, "Golden cross scan completed")


@router.get(
    "/sell-signal/{symbol}",
    response_model=ResponseDTO[SellSignalAnalysisDTO],
    status_code=status.HTTP_200_OK,
    summary="매도 시그널 분석",
    description="종목의 기술적 지표를 분석하여 매도 시그널 판단 (MA + Stochastic + RSI)",
)
async def analyze_sell_signal(
    symbol: str,
    session: DatabaseSession,
    market_data_service: MarketDataServiceDep,
    stoch_overbought: float = Query(default=70.0, ge=50.0, le=90.0, description="Stochastic 과매수 임계값"),
    rsi_overbought: float = Query(default=70.0, ge=50.0, le=90.0, description="RSI 과매수 임계값"),
) -> ResponseDTO[SellSignalAnalysisDTO]:
    """
    매도 시그널 분석

    종목의 기술적 지표를 분석하여 매도 추천을 제공합니다.

    분석 지표:
    - MA40/MA160: 데드크로스 여부 (MA40 < MA160)
    - Stochastic: 과매수 여부 (K > 70)
    - RSI: 과매수 여부 (RSI > 70)

    매도 추천 등급:
    - HOLD: 보유 유지 (시그널 없음)
    - WATCH: 관망 (약한 시그널)
    - WEAK_SELL: 약한 매도
    - CONSIDER_SELL: 매도 고려
    - SELL: 매도 권장
    - STRONG_SELL: 강력 매도
    """
    service = StrategyService(session)
    result = await service.analyze_sell_signal(
        symbol=symbol,
        stoch_overbought=stoch_overbought,
        rsi_overbought=rsi_overbought,
    )

    # 종목명 조회 및 추가 (DB 우선, API 폴백 - ETF 지원)
    if result.name is None:
        from src.adapters.database.repositories.stock_universe_repository import (
            StockUniverseRepository,
        )
        try:
            universe_repo = StockUniverseRepository(session)
            stock = await universe_repo.get_by_symbol(symbol)
            if stock and stock.name:
                result.name = stock.name
            else:
                # DB에 없으면 API로 조회 (일반주식 + ETF 지원)
                stock_name = await market_data_service.get_stock_name(symbol)
                if stock_name:
                    result.name = stock_name
        except Exception:
            pass  # 종목명 조회 실패 시 무시

    return ResponseDTO.success_response(result, "Sell signal analysis completed")


# ==================== Analysis History Endpoints (정적 경로) ====================


@router.post(
    "/analysis-history",
    response_model=ResponseDTO[AnalysisHistoryDTO],
    status_code=status.HTTP_201_CREATED,
    summary="분석 이력 저장",
    description="매수/매도 분석 결과를 DB에 저장",
)
async def create_analysis_history(
    request: AnalysisHistoryCreateDTO,
) -> ResponseDTO[AnalysisHistoryDTO]:
    """분석 이력 저장 - @transaction이 세션을 관리"""
    service = StrategyService()
    history = await service.save_analysis_history(request)
    return ResponseDTO.success_response(history, "Analysis history saved successfully")


@router.get(
    "/analysis-history",
    response_model=ResponseDTO[AnalysisHistoryListDTO],
    status_code=status.HTTP_200_OK,
    summary="분석 이력 목록 조회",
    description="매수/매도 분석 이력 목록 조회",
)
async def get_analysis_history_list(
    session: DatabaseSession,
    analysis_type: str = Query(..., description="분석 유형 (buy/sell)"),
    is_active: bool | None = Query(default=None, description="활성 추적 여부 필터"),
    limit: int = Query(default=50, ge=1, le=200, description="최대 조회 개수"),
    offset: int = Query(default=0, ge=0, description="시작 위치"),
) -> ResponseDTO[AnalysisHistoryListDTO]:
    """분석 이력 목록 조회"""
    service = StrategyService(session)
    history_list = await service.list_analysis_history(
        analysis_type=analysis_type,
        is_active=is_active,
        limit=limit,
        offset=offset,
    )
    return ResponseDTO.success_response(history_list, "Analysis history list retrieved successfully")


@router.get(
    "/analysis-history/{history_id}",
    response_model=ResponseDTO[AnalysisHistoryDTO],
    status_code=status.HTTP_200_OK,
    summary="분석 이력 상세 조회",
    description="분석 이력 ID로 상세 정보 조회",
)
async def get_analysis_history(
    history_id: int,
    session: DatabaseSession,
) -> ResponseDTO[AnalysisHistoryDTO]:
    """분석 이력 상세 조회"""
    service = StrategyService(session)
    history = await service.get_analysis_history(history_id)
    return ResponseDTO.success_response(history, "Analysis history retrieved successfully")


@router.post(
    "/analysis-history/refresh",
    response_model=ResponseDTO[AnalysisHistoryRefreshResultDTO],
    status_code=status.HTTP_200_OK,
    summary="분석 이력 일괄 갱신",
    description="활성 추적 중인 종목들의 분석 이력을 일괄 갱신",
)
async def refresh_analysis_history(
    market_data_service: MarketDataServiceDep,
    analysis_type: str = Query(..., description="분석 유형 (buy/sell)"),
) -> ResponseDTO[AnalysisHistoryRefreshResultDTO]:
    """분석 이력 일괄 갱신 - @transaction이 세션을 관리"""
    service = StrategyService()
    result = await service.refresh_analysis_history(analysis_type, market_data_service)
    return ResponseDTO.success_response(result, "Analysis history refresh completed")


@router.patch(
    "/analysis-history/{history_id}/active",
    response_model=ResponseDTO[AnalysisHistoryDTO],
    status_code=status.HTTP_200_OK,
    summary="활성 추적 상태 변경",
    description="분석 이력의 활성 추적 상태 변경",
)
async def update_analysis_history_active(
    history_id: int,
    is_active: bool = Query(..., description="활성 추적 여부"),
) -> ResponseDTO[AnalysisHistoryDTO]:
    """활성 추적 상태 변경 - @transaction이 세션을 관리"""
    service = StrategyService()
    history = await service.set_analysis_history_active(history_id, is_active)
    return ResponseDTO.success_response(history, "Analysis history active status updated")


@router.delete(
    "/analysis-history/{history_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="분석 이력 삭제",
    description="분석 이력 삭제",
)
async def delete_analysis_history(
    history_id: int,
) -> None:
    """분석 이력 삭제 - @transaction이 세션을 관리"""
    service = StrategyService()
    await service.delete_analysis_history(history_id)


# ==================== Scheduler Status (정적 경로) ====================


@router.get(
    "/scheduler/status",
    response_model=ResponseDTO[dict],
    status_code=status.HTTP_200_OK,
    summary="스케줄러 상태 조회",
    description="전략 스케줄러 상태 및 예정 작업 조회",
)
async def get_scheduler_status() -> ResponseDTO[dict]:
    """스케줄러 상태 조회"""
    from src.application.domain.strategy.scheduler import get_strategy_scheduler

    scheduler = get_strategy_scheduler()
    status_info = scheduler.get_status()
    return ResponseDTO.success_response(status_info, "Scheduler status retrieved")


# ==================== 동적 경로 (/{strategy_id}) ====================


@router.get(
    "/{strategy_id}",
    response_model=ResponseDTO[StrategyDetailResponseDTO],
    status_code=status.HTTP_200_OK,
    summary="전략 상세 조회",
    description="전략 ID로 상세 정보 조회",
)
async def get_strategy(
    strategy_id: int,
    session: DatabaseSession,
) -> ResponseDTO[StrategyDetailResponseDTO]:
    """전략 상세 조회"""
    service = StrategyService(session)
    strategy_data = await service.get_strategy(strategy_id)
    return ResponseDTO.success_response(strategy_data, "Strategy retrieved successfully")


@router.patch(
    "/{strategy_id}",
    response_model=ResponseDTO[StrategyDetailResponseDTO],
    status_code=status.HTTP_200_OK,
    summary="전략 수정",
    description="전략 정보 수정",
)
async def update_strategy(
    strategy_id: int,
    request: StrategyUpdateRequestDTO,
) -> ResponseDTO[StrategyDetailResponseDTO]:
    """전략 수정 - @transaction이 세션을 관리"""
    service = StrategyService()
    strategy_data = await service.update_strategy(strategy_id, request)
    return ResponseDTO.success_response(strategy_data, "Strategy updated successfully")


@router.delete(
    "/{strategy_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="전략 삭제",
    description="전략 삭제 (Soft Delete)",
)
async def delete_strategy(
    strategy_id: int,
) -> None:
    """전략 삭제 - @transaction이 세션을 관리"""
    service = StrategyService()
    await service.delete_strategy(strategy_id)


# ==================== 전략 상태 관리 ====================


@router.post(
    "/{strategy_id}/start",
    response_model=ResponseDTO[StrategyDetailResponseDTO],
    status_code=status.HTTP_200_OK,
    summary="전략 시작",
    description="전략 활성화 (자동매매 시작)",
)
async def start_strategy(
    strategy_id: int,
) -> ResponseDTO[StrategyDetailResponseDTO]:
    """전략 시작 - @transaction이 세션을 관리"""
    service = StrategyService()
    strategy_data = await service.start_strategy(strategy_id)
    return ResponseDTO.success_response(strategy_data, "Strategy started successfully")


@router.post(
    "/{strategy_id}/pause",
    response_model=ResponseDTO[StrategyDetailResponseDTO],
    status_code=status.HTTP_200_OK,
    summary="전략 일시정지",
    description="전략 일시정지 (자동매매 일시 중단)",
)
async def pause_strategy(
    strategy_id: int,
) -> ResponseDTO[StrategyDetailResponseDTO]:
    """전략 일시정지 - @transaction이 세션을 관리"""
    service = StrategyService()
    strategy_data = await service.pause_strategy(strategy_id)
    return ResponseDTO.success_response(strategy_data, "Strategy paused successfully")


@router.post(
    "/{strategy_id}/stop",
    response_model=ResponseDTO[StrategyDetailResponseDTO],
    status_code=status.HTTP_200_OK,
    summary="전략 중지",
    description="전략 완전 중지 (자동매매 종료)",
)
async def stop_strategy(
    strategy_id: int,
) -> ResponseDTO[StrategyDetailResponseDTO]:
    """전략 중지 - @transaction이 세션을 관리"""
    service = StrategyService()
    strategy_data = await service.stop_strategy(strategy_id)
    return ResponseDTO.success_response(strategy_data, "Strategy stopped successfully")


# ==================== Golden Cross Strategy Endpoints ====================


@router.get(
    "/{strategy_id}/config",
    response_model=ResponseDTO[GoldenCrossConfigDTO],
    status_code=status.HTTP_200_OK,
    summary="전략 설정 조회",
    description="골든크로스 전략 설정 조회",
)
async def get_strategy_config(
    strategy_id: int,
    session: DatabaseSession,
) -> ResponseDTO[GoldenCrossConfigDTO]:
    """전략 설정 조회"""
    service = StrategyService(session)
    config = await service.get_golden_cross_config(strategy_id)
    return ResponseDTO.success_response(config, "Strategy config retrieved successfully")


@router.patch(
    "/{strategy_id}/config",
    response_model=ResponseDTO[GoldenCrossConfigDTO],
    status_code=status.HTTP_200_OK,
    summary="전략 설정 수정",
    description="골든크로스 전략 설정 수정",
)
async def update_strategy_config(
    strategy_id: int,
    config: GoldenCrossConfigDTO,
) -> ResponseDTO[GoldenCrossConfigDTO]:
    """전략 설정 수정 - @transaction이 세션을 관리"""
    service = StrategyService()
    updated_config = await service.update_golden_cross_config(strategy_id, config)
    return ResponseDTO.success_response(updated_config, "Strategy config updated successfully")


@router.get(
    "/{strategy_id}/symbol-states",
    response_model=ResponseDTO[SymbolStateListDTO],
    status_code=status.HTTP_200_OK,
    summary="종목별 상태 조회",
    description="골든크로스 전략의 종목별 상태 머신 조회",
)
async def get_symbol_states(
    strategy_id: int,
    session: DatabaseSession,
) -> ResponseDTO[SymbolStateListDTO]:
    """종목별 상태 조회"""
    service = StrategyService(session)
    states = await service.get_symbol_states(strategy_id)
    return ResponseDTO.success_response(states, "Symbol states retrieved successfully")


@router.get(
    "/{strategy_id}/signals",
    response_model=ResponseDTO[SignalListDTO],
    status_code=status.HTTP_200_OK,
    summary="시그널 이력 조회",
    description="전략의 매수/매도 시그널 이력 조회",
)
async def get_signals(
    strategy_id: int,
    session: DatabaseSession,
    limit: int = Query(default=50, ge=1, le=200, description="최대 조회 개수"),
    offset: int = Query(default=0, ge=0, description="시작 위치"),
) -> ResponseDTO[SignalListDTO]:
    """시그널 이력 조회"""
    service = StrategyService(session)
    signals = await service.get_signals(strategy_id, limit, offset)
    return ResponseDTO.success_response(signals, "Signals retrieved successfully")


@router.get(
    "/{strategy_id}/signals/statistics",
    response_model=ResponseDTO[SignalStatisticsDTO],
    status_code=status.HTTP_200_OK,
    summary="시그널 통계 조회",
    description="전략의 시그널 통계 (승률, 수익 등) 조회",
)
async def get_signal_statistics(
    strategy_id: int,
    session: DatabaseSession,
    days: int = Query(default=30, ge=1, le=365, description="조회 기간 (일)"),
) -> ResponseDTO[SignalStatisticsDTO]:
    """시그널 통계 조회"""
    service = StrategyService(session)
    stats = await service.get_signal_statistics(strategy_id, days)
    return ResponseDTO.success_response(stats, "Signal statistics retrieved successfully")


@router.post(
    "/{strategy_id}/execute",
    response_model=ResponseDTO[StrategyExecuteResultDTO],
    status_code=status.HTTP_200_OK,
    summary="전략 수동 실행",
    description="골든크로스 전략 수동 실행 (테스트용, 기본 dry_run=true)",
)
async def execute_strategy(
    strategy_id: int,
    request: StrategyExecuteRequestDTO,
    session: DatabaseSession,
) -> ResponseDTO[StrategyExecuteResultDTO]:
    """전략 수동 실행"""
    service = StrategyService(session)
    result = await service.execute_golden_cross(
        strategy_id,
        request.dry_run,
        request.force,
    )
    return ResponseDTO.success_response(result, "Strategy execution completed")
