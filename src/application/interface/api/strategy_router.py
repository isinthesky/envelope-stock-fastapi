# -*- coding: utf-8 -*-
"""
Strategy Router - 전략 관리 API 엔드포인트

NOTE: 라우터 순서 중요!
- 정적 경로 (/universe, /scheduler/status)를 동적 경로 (/{strategy_id}) 앞에 정의
- FastAPI는 순서대로 경로를 매칭하므로 동적 경로가 먼저 오면 정적 경로가 무시됨

세션 계약 (2026-01-14 업데이트):
- StrategyService는 DI로 주입받음 (StrategyServiceDep)
- 서비스 메서드는 @transaction 데코레이터가 session을 자동 주입
"""

from fastapi import APIRouter, Query, status

from src.application.common.exceptions import ServiceUnavailableError

from src.application.common.dependencies import (
    BuyStrategyServiceDep,
    MarketDataServiceDep,
    StrategyServiceDep,
    StrategySymbolStateRepositoryDep,
    StockUniverseRepositoryDep,
)
from src.application.common.dto import ResponseDTO
from src.application.domain.strategy.dto import (
    AnalysisHistoryCreateDTO,
    AnalysisHistoryDTO,
    AnalysisHistoryListDTO,
    AnalysisHistoryRefreshResultDTO,
    AnalysisHistoryUpdateDTO,
    GoldenCrossConfigDTO,
    GoldenCrossScanListDTO,
    MA5BreakoutScanListDTO,
    SellSignalAnalysisDTO,
    SignalListDTO,
    SignalStatisticsDTO,
    StockUniverseListDTO,
    UniverseRefreshResultDTO,
    StrategyCreateRequestDTO,
    StrategyDetailResponseDTO,
    StrategyExecuteRequestDTO,
    StrategyExecuteResultDTO,
    StrategyListResponseDTO,
    StrategyUpdateRequestDTO,
    SymbolStateListDTO,
)

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
    service: StrategyServiceDep,
) -> ResponseDTO[StrategyDetailResponseDTO]:
    """전략 생성 - @transaction이 세션을 관리"""
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
    service: StrategyServiceDep,
    account_no: str | None = None,
    status_filter: str | None = None,
) -> ResponseDTO[StrategyListResponseDTO]:
    """전략 목록 조회 - @transaction이 세션을 관리"""
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
    service: StrategyServiceDep,
    market: str | None = Query(default=None, description="시장 구분 (KOSPI/KOSDAQ)"),
    eligible_only: bool = Query(default=True, description="스크리닝 통과 종목만"),
    limit: int = Query(default=1000, ge=1, le=5000, description="(eligible_only=true일 때) 최대 조회 개수"),
) -> ResponseDTO[StockUniverseListDTO]:
    """종목 유니버스 조회 - @transaction이 세션을 관리"""
    universe = await service.get_stock_universe(market, eligible_only, limit=limit)
    return ResponseDTO.success_response(universe, "Universe retrieved successfully")


@router.post(
    "/universe/refresh",
    response_model=ResponseDTO[UniverseRefreshResultDTO],
    status_code=status.HTTP_200_OK,
    summary="유니버스 갱신",
    description="종목 유니버스 데이터 갱신",
)
async def refresh_universe(
    service: StrategyServiceDep,
    market_data_service: MarketDataServiceDep,
) -> ResponseDTO[UniverseRefreshResultDTO]:
    """유니버스 갱신 - @transaction이 세션을 관리"""
    if not market_data_service.has_valid_credentials():
        raise ServiceUnavailableError("KIS API credentials not configured")

    result = await service.refresh_universe()
    dto = UniverseRefreshResultDTO(**result)
    # ResponseDTO.success는 작업 결과(dto.success)와 일치시키는 것이 운영/클라이언트 측에서 혼동이 적음
    message = "Universe refresh completed" if dto.success else (dto.message or "Universe refresh failed")
    error = None if dto.success else {"timed_out": dto.timed_out, "message": dto.message}
    return ResponseDTO(success=dto.success, message=message, data=dto, error=error)


@router.get(
    "/universe/golden-cross-scan",
    response_model=ResponseDTO[GoldenCrossScanListDTO],
    status_code=status.HTTP_200_OK,
    summary="골든크로스 종목 스캔",
    description="유니버스 종목에 대해 기술적 지표를 계산하고 골든크로스 조건에 부합하는 종목 필터링",
)
async def scan_golden_cross(
    service: StrategyServiceDep,
    market: str | None = Query(default=None, description="시장 구분 (KOSPI/KOSDAQ/ETF)"),
    stoch_threshold: float = Query(default=30.0, ge=10.0, le=50.0, description="Stochastic 과매도 임계값"),
    gc_only: bool = Query(default=True, description="골든크로스 활성 종목만 반환"),
    include_etf: bool = Query(default=True, description="ETF 종목 포함 여부"),
    limit: int = Query(default=1000, ge=1, le=5000, description="스캔 대상 최대 종목 수"),
    max_concurrent: int | None = Query(
        default=None, ge=1, le=50, description="동시 처리 수 (미지정 시 설정값 사용)"
    ),
) -> ResponseDTO[GoldenCrossScanListDTO]:
    """
    골든크로스 종목 스캔 - @transaction이 세션을 관리

    스크리닝 통과 종목에 대해 MA55, MA165, Stochastic K/D 지표를 계산하고
    골든크로스 전략 조건에 따라 종목을 필터링합니다.

    상태:
    - OPTIMAL_BUY: K<25, K>D, MA갭 0~5% (매수 적기)
    - READY_TO_BUY: 골든크로스 활성 + Stochastic 과매도 (매수 준비)
    - WAITING_FOR_PULLBACK: 골든크로스 활성 + Stochastic 중간 (눌림목 대기)
    - GC_ACTIVE: 골든크로스 활성 + Stochastic 과매수 (대기)
    - NOT_GC: 골든크로스 비활성 (MA55 < MA165)

    ETF 종목은 시가총액/거래량 조건이 완화되어 적용됩니다.
    """
    result = await service.scan_golden_cross_candidates(
        market=market,
        stoch_threshold=stoch_threshold,
        gc_only=gc_only,
        include_etf=include_etf,
        limit=limit,
        max_concurrent=max_concurrent,
    )
    return ResponseDTO.success_response(result, "Golden cross scan completed")


@router.post(
    "/universe/golden-cross-scan-symbols",
    response_model=ResponseDTO[GoldenCrossScanListDTO],
    status_code=status.HTTP_200_OK,
    summary="특정 종목 골든크로스 스캔",
    description="지정한 종목 목록에 대해 골든크로스 스캔 (ETF 등 유니버스 외 종목 스캔용)",
)
async def scan_golden_cross_symbols(
    symbols: list[dict],
    buy_service: BuyStrategyServiceDep,
    stoch_threshold: float = Query(default=30.0, ge=10.0, le=50.0, description="Stochastic 과매도 임계값"),
    gc_only: bool = Query(default=True, description="골든크로스 활성 종목만 반환"),
) -> ResponseDTO[GoldenCrossScanListDTO]:
    """
    특정 종목 목록에 대해 골든크로스 스캔 - @transaction이 세션을 관리

    stock_universe에 없는 ETF, ETN 등의 종목도 직접 스캔할 수 있습니다.

    Request Body:
    ```json
    [
        {"symbol": "441800", "name": "타임폴리오 ETF", "market": "ETF"},
        {"symbol": "466920", "name": "신한 SOL 조선", "market": "ETF"}
    ]
    ```
    """
    result = await buy_service.scan_symbols(
        symbols=symbols,
        stoch_threshold=stoch_threshold,
        gc_only=gc_only,
    )
    return ResponseDTO.success_response(result, "Golden cross scan completed")


@router.get(
    "/universe/ma5-breakout-scan",
    response_model=ResponseDTO[MA5BreakoutScanListDTO],
    status_code=status.HTTP_200_OK,
    summary="MA5 돌파 종목 스캔",
    description="MA5가 MA300의 0.7% 상단을 돌파한 종목 필터링",
)
async def scan_ma5_breakout(
    buy_service: BuyStrategyServiceDep,
    market: str | None = Query(default=None, description="시장 구분 (KOSPI/KOSDAQ/ETF)"),
    short_period: int = Query(default=5, ge=3, le=20, description="단기 MA 기간"),
    long_period: int = Query(default=300, ge=100, le=500, description="장기 MA 기간"),
    envelope_pct: float = Query(default=0.7, ge=0.1, le=3.0, description="엔벨로프 %"),
    use_volume_filter: bool = Query(default=True, description="거래량 필터 사용"),
    include_etf: bool = Query(default=True, description="ETF 종목 포함 여부"),
    limit: int = Query(default=1000, ge=1, le=5000, description="스캔 대상 최대 종목 수"),
    max_concurrent: int | None = Query(
        default=None, ge=1, le=50, description="동시 처리 수 (미지정 시 설정값 사용)"
    ),
) -> ResponseDTO[MA5BreakoutScanListDTO]:
    """
    MA5 돌파 종목 스캔 - @transaction이 세션을 관리

    매수 조건:
    - MA5 > MA300 × (1 + envelope_pct/100)
    - 현재가 > MA300 상단
    - 거래량 ≥ 20일 평균 (선택)

    상태:
    - BREAKOUT: 오늘 돌파 (이전에 상단 아래 → 현재 상단 위)
    - ABOVE: 이미 상단 위에서 거래 중
    - BELOW: 상단 아래
    """
    result = await buy_service.scan_ma5_breakout_candidates(
        market=market,
        short_period=short_period,
        long_period=long_period,
        envelope_pct=envelope_pct,
        use_volume_filter=use_volume_filter,
        include_etf=include_etf,
        limit=limit,
        max_concurrent=max_concurrent,
    )
    return ResponseDTO.success_response(result, "MA5 breakout scan completed")


@router.post(
    "/universe/ma5-breakout-scan-symbols",
    response_model=ResponseDTO[MA5BreakoutScanListDTO],
    status_code=status.HTTP_200_OK,
    summary="특정 종목 MA5 돌파 스캔",
    description="지정한 종목 목록에 대해 MA5 돌파 스캔",
)
async def scan_ma5_breakout_symbols(
    symbols: list[dict],
    buy_service: BuyStrategyServiceDep,
    short_period: int = Query(default=5, ge=3, le=20, description="단기 MA 기간"),
    long_period: int = Query(default=300, ge=100, le=500, description="장기 MA 기간"),
    envelope_pct: float = Query(default=0.7, ge=0.1, le=3.0, description="엔벨로프 %"),
    use_volume_filter: bool = Query(default=True, description="거래량 필터 사용"),
) -> ResponseDTO[MA5BreakoutScanListDTO]:
    """
    특정 종목 목록에 대해 MA5 돌파 스캔 - @transaction이 세션을 관리

    Request Body:
    ```json
    [
        {"symbol": "005930", "name": "삼성전자", "market": "KOSPI"},
        {"symbol": "000660", "name": "SK하이닉스", "market": "KOSPI"}
    ]
    ```
    """
    result = await buy_service.scan_ma5_breakout_symbols(
        symbols=symbols,
        short_period=short_period,
        long_period=long_period,
        envelope_pct=envelope_pct,
        use_volume_filter=use_volume_filter,
    )
    return ResponseDTO.success_response(result, "MA5 breakout scan completed")


@router.post(
    "/universe/financial-filter",
    response_model=ResponseDTO[GoldenCrossScanListDTO],
    status_code=status.HTTP_200_OK,
    summary="재무 필터 적용 (2차 필터)",
    description="골든크로스 스캔 결과에 DART 재무제표 기반 필터 적용",
)
async def apply_financial_filter(
    scan_result: GoldenCrossScanListDTO,
    buy_service: BuyStrategyServiceDep,
    target_states: list[str] | None = Query(
        default=None,
        description="필터 적용 대상 상태 (기본: OPTIMAL_BUY, BUY_INTEREST, READY_TO_BUY)"
    ),
) -> ResponseDTO[GoldenCrossScanListDTO]:
    """
    재무 필터 적용 (2차 필터) - DART API 기반

    골든크로스 스캔 결과에 대해 재무제표 데이터를 조회하여 필터링합니다.

    필터 조건:
    - 매출 YoY ≥ 0% (구조적 성장/유지)
    - 영업이익 2년 연속 흑자 (턴어라운드 제외)
    - 적자→흑자 전환은 TURNAROUND로 별도 분류

    결과 상태:
    - PASS: 재무 필터 통과
    - FAIL: 재무 필터 미통과
    - TURNAROUND: 적자→흑자 전환 (별도 버킷)
    - PENDING: 필터 대상 아님
    - ERROR: 데이터 조회 실패

    주의: DART API 일일 호출 한도(10,000건)가 있으므로 과도한 요청 주의
    """
    result = await buy_service.apply_financial_filter(
        scan_result=scan_result,
        target_states=target_states,
    )
    return ResponseDTO.success_response(result, "Financial filter applied")


@router.get(
    "/sell-signal/{symbol}",
    response_model=ResponseDTO[SellSignalAnalysisDTO],
    status_code=status.HTTP_200_OK,
    summary="매도 시그널 분석",
    description="종목의 기술적 지표를 분석하여 매도 시그널 판단 (MA + Stochastic + RSI + Phase)",
)
async def analyze_sell_signal(
    symbol: str,
    service: StrategyServiceDep,
    market_data_service: MarketDataServiceDep,
    state_repo: StrategySymbolStateRepositoryDep,
    universe_repo: StockUniverseRepositoryDep,
    stoch_overbought: float = Query(default=70.0, ge=50.0, le=90.0, description="Stochastic 과매수 임계값"),
    rsi_overbought: float = Query(default=70.0, ge=50.0, le=90.0, description="RSI 과매수 임계값"),
    entry_price: float | None = Query(default=None, ge=0.0, description="진입가 (수익률 기반 동적 임계값 적용)"),
    strategy_id: int | None = Query(default=None, ge=1, description="전략 ID (보유 종목 진입가 자동 조회)"),
) -> ResponseDTO[SellSignalAnalysisDTO]:
    """
    매도 시그널 분석 - @transaction이 세션을 관리

    종목의 기술적 지표를 분석하여 매도 추천을 제공합니다.

    분석 지표:
    - MA55/MA165: 데드크로스 여부 (MA55 < MA165)
    - Stochastic: 과매수 여부 (K > 70)
    - RSI: 과매수 여부 (RSI > 70)

    Phase 기반 선제적 매도 시그널:
    - PHASE_1: 골든크로스 유지 + 극심한 과열 (수익 보호)
    - PHASE_2: MA 갭 축소 + 과열 (데드크로스 임박)
    - PHASE_3~5: 데드크로스 + 과열 수준별 매도 권장

    수익률 기반 동적 임계값:
    - entry_price 제공 시 수익률에 따라 임계값 자동 조정
    - strategy_id 제공 시 보유 종목의 진입가 자동 조회

    매도 추천 등급:
    - HOLD: 보유 유지 (시그널 없음)
    - WATCH: 관망 (약한 시그널)
    - WEAK_SELL: 약한 매도
    - CONSIDER_SELL: 매도 고려
    - SELL: 매도 권장
    - STRONG_SELL: 강력 매도
    """
    # 전략 ID가 제공되면 보유 종목의 진입가/최고가 자동 조회
    highest_price: float | None = None
    trailing_stop_activated: bool = False

    if strategy_id is not None and entry_price is None:
        try:
            # NOTE: state_repo는 DI로 주입받고, @transaction이 없으므로 session 없이 조회
            # Repository는 _get_session에서 session 없으면 에러 발생
            # 여기서는 단순 조회이므로 새 session으로 조회 필요 - 서비스 메서드로 위임 권장
            # 임시 해결: get_by_strategy_and_symbol이 session 없이 동작하도록 adapter 패턴 유지
            state = await service.get_symbol_state_for_sell_signal(strategy_id, symbol)
            if state and state.get("entry_price"):
                entry_price = state["entry_price"]
                if state.get("highest_price"):
                    highest_price = state["highest_price"]
                trailing_stop_activated = state.get("trailing_stop_activated", False)
        except Exception:
            pass  # 조회 실패 시 무시

    result = await service.analyze_sell_signal(
        symbol=symbol,
        stoch_overbought=stoch_overbought,
        rsi_overbought=rsi_overbought,
        entry_price=entry_price,
        highest_price=highest_price,
        trailing_stop_activated=trailing_stop_activated,
    )

    # 종목명 조회 및 추가 (DB 우선, API 폴백 - ETF 지원)
    if result.name is None:
        try:
            stock_name = await service.get_stock_name_for_sell_signal(symbol)
            if stock_name:
                result.name = stock_name
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
    service: StrategyServiceDep,
) -> ResponseDTO[AnalysisHistoryDTO]:
    """분석 이력 저장 - @transaction이 세션을 관리"""
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
    service: StrategyServiceDep,
    analysis_type: str = Query(..., description="분석 유형 (buy/sell)"),
    is_active: bool | None = Query(default=None, description="활성 추적 여부 필터"),
    limit: int = Query(default=50, ge=1, le=200, description="최대 조회 개수"),
    offset: int = Query(default=0, ge=0, description="시작 위치"),
) -> ResponseDTO[AnalysisHistoryListDTO]:
    """분석 이력 목록 조회 - @transaction이 세션을 관리"""
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
    service: StrategyServiceDep,
) -> ResponseDTO[AnalysisHistoryDTO]:
    """분석 이력 상세 조회 - @transaction이 세션을 관리"""
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
    service: StrategyServiceDep,
    market_data_service: MarketDataServiceDep,
    analysis_type: str = Query(..., description="분석 유형 (buy/sell)"),
) -> ResponseDTO[AnalysisHistoryRefreshResultDTO]:
    """분석 이력 일괄 갱신 - @transaction이 세션을 관리"""
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
    service: StrategyServiceDep,
    is_active: bool = Query(..., description="활성 추적 여부"),
) -> ResponseDTO[AnalysisHistoryDTO]:
    """활성 추적 상태 변경 - @transaction이 세션을 관리"""
    history = await service.set_analysis_history_active(history_id, is_active)
    return ResponseDTO.success_response(history, "Analysis history active status updated")


@router.patch(
    "/analysis-history/{history_id}",
    response_model=ResponseDTO[AnalysisHistoryDTO],
    status_code=status.HTTP_200_OK,
    summary="분석 이력 수정",
    description="분석 이력의 진입가, 메모 등 수정",
)
async def update_analysis_history(
    history_id: int,
    request: AnalysisHistoryUpdateDTO,
    service: StrategyServiceDep,
) -> ResponseDTO[AnalysisHistoryDTO]:
    """분석 이력 수정 - @transaction이 세션을 관리"""
    history = await service.update_analysis_history(
        history_id=history_id,
        entry_price=request.entry_price,
        note=request.note,
    )
    return ResponseDTO.success_response(history, "Analysis history updated successfully")


@router.delete(
    "/analysis-history/{history_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="분석 이력 삭제",
    description="분석 이력 삭제",
)
async def delete_analysis_history(
    history_id: int,
    service: StrategyServiceDep,
) -> None:
    """분석 이력 삭제 - @transaction이 세션을 관리"""
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
    service: StrategyServiceDep,
) -> ResponseDTO[StrategyDetailResponseDTO]:
    """전략 상세 조회 - @transaction이 세션을 관리"""
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
    service: StrategyServiceDep,
) -> ResponseDTO[StrategyDetailResponseDTO]:
    """전략 수정 - @transaction이 세션을 관리"""
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
    service: StrategyServiceDep,
) -> None:
    """전략 삭제 - @transaction이 세션을 관리"""
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
    service: StrategyServiceDep,
) -> ResponseDTO[StrategyDetailResponseDTO]:
    """전략 시작 - @transaction이 세션을 관리"""
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
    service: StrategyServiceDep,
) -> ResponseDTO[StrategyDetailResponseDTO]:
    """전략 일시정지 - @transaction이 세션을 관리"""
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
    service: StrategyServiceDep,
) -> ResponseDTO[StrategyDetailResponseDTO]:
    """전략 중지 - @transaction이 세션을 관리"""
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
    service: StrategyServiceDep,
) -> ResponseDTO[GoldenCrossConfigDTO]:
    """전략 설정 조회 - @transaction이 세션을 관리"""
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
    service: StrategyServiceDep,
) -> ResponseDTO[GoldenCrossConfigDTO]:
    """전략 설정 수정 - @transaction이 세션을 관리"""
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
    service: StrategyServiceDep,
) -> ResponseDTO[SymbolStateListDTO]:
    """종목별 상태 조회 - @transaction이 세션을 관리"""
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
    service: StrategyServiceDep,
    limit: int = Query(default=50, ge=1, le=200, description="최대 조회 개수"),
    offset: int = Query(default=0, ge=0, description="시작 위치"),
) -> ResponseDTO[SignalListDTO]:
    """시그널 이력 조회 - @transaction이 세션을 관리"""
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
    service: StrategyServiceDep,
    days: int = Query(default=30, ge=1, le=365, description="조회 기간 (일)"),
) -> ResponseDTO[SignalStatisticsDTO]:
    """시그널 통계 조회 - @transaction이 세션을 관리"""
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
    service: StrategyServiceDep,
) -> ResponseDTO[StrategyExecuteResultDTO]:
    """전략 수동 실행 - @transaction이 세션을 관리"""
    result = await service.execute_golden_cross(
        strategy_id,
        request.dry_run,
        request.force,
    )
    return ResponseDTO.success_response(result, "Strategy execution completed")
