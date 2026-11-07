# -*- coding: utf-8 -*-
"""
Backtest Router - 백테스팅 API 엔드포인트
"""

from datetime import date, datetime, time

from fastapi import APIRouter, Depends, HTTPException, Query

from src.application.common.dependencies import (
    AdminAccessDep,
    DatabaseSession,
    get_kis_client,
    get_redis_client,
)
from src.application.domain.backtest.dto import (
    BacktestConfigDTO,
    BacktestRequestDTO,
    BacktestResultDTO,
    ExecutionTiming,
    MultiSymbolBacktestRequestDTO,
    MultiSymbolBacktestResultDTO,
    UniverseBacktestRequestDTO,
    UniverseBacktestResultDTO,
    WalkForwardReportDTO,
)
from src.application.domain.backtest.report_reader import WalkForwardReportReader
from src.application.domain.backtest.service import BacktestService
from src.application.domain.market_data.service import MarketDataService
from src.application.domain.strategy.buy_strategy_service import BuyStrategyService
from src.application.domain.strategy.dto import StrategyConfigDTO
from src.application.domain.strategy.risk_contract import DEFAULT_PEAK_DRAWDOWN_STOP_RATIO
from src.settings.config import settings

router = APIRouter(prefix="/api/v1/backtest", tags=["Backtest"])


async def get_backtest_service(
    session: DatabaseSession,
    kis_client=Depends(get_kis_client),
    redis_client=Depends(get_redis_client),
) -> BacktestService:
    market_data_service = MarketDataService(kis_client, redis_client)
    return BacktestService(market_data_service, db_session=session)


@router.post("/run", response_model=BacktestResultDTO)
async def run_backtest(
    request: BacktestRequestDTO,
    service: BacktestService = Depends(get_backtest_service),
    admin_access: AdminAccessDep = None,
):
    return await service.run_backtest(request)


@router.post("/run-multi", response_model=MultiSymbolBacktestResultDTO)
async def run_multi_symbol_backtest(
    request: MultiSymbolBacktestRequestDTO,
    service: BacktestService = Depends(get_backtest_service),
    admin_access: AdminAccessDep = None,
):
    return await service.run_multi_symbol_backtest(request)


_SELECTION_NOTE = (
    "종목 선정은 오늘의 GC 상태/전체기간 수익률을 사용하지 않는다(look-ahead 제거). "
    "단, 유니버스 구성·적격성(eligible_only)은 현재 스냅샷이라 생존편향이 남는다. "
    "결과의 best/worst 정렬은 사후(post-hoc) 진단값이다."
)


async def _select_universe_symbols(
    request: UniverseBacktestRequestDTO,
    session,
    base_strategy_params: dict,
    short_ma: int,
    long_ma: int,
) -> tuple[list[str], str]:
    """백테스트 대상 종목을 **시그널 상태와 무관하게** 고른다.

    이전 구현은 오늘 스캔의 gc_state(OPTIMAL_BUY 등)로 거르고 그 순서를 썼다 →
    백테스트 기간 이후 정보(오늘의 상태)로 종목을 고르는 look-ahead.
    """
    if request.symbols:
        fixed: list[str] = []
        for raw in request.symbols:
            sym = raw.strip()
            if sym and sym not in fixed:
                fixed.append(sym)
        return fixed[: request.limit], "fixed_symbols(user_provided)"

    # include_etf: 명시값 우선, 미지정(None)이면 운영 유니버스 모드를 기본 적용
    include_etf = (
        request.include_etf if request.include_etf is not None else settings.etf_universe_enabled
    )
    buy_service = BuyStrategyService(session=session)
    scan = await buy_service.scan_golden_cross_candidates(
        market=request.market,
        stoch_threshold=float(base_strategy_params.get("stoch_oversold", 30.0)),
        gc_only=False,
        include_etf=include_etf,
        limit=max(request.limit * 5, request.limit),
        short_ma_period=short_ma,
        long_ma_period=long_ma,
    )
    items = list(scan.stocks)
    if request.eligible_only:
        items = [item for item in items if item.screening_score is not None]
    # gc_state/점수 정렬을 쓰지 않고 종목코드 순으로 결정적 선택(미래 정보 없음)
    ordered = sorted({item.symbol for item in items})
    return ordered[: request.limit], "current_universe_symbol_order(no_signal_state_filter)"


@router.post("/run-universe-golden-cross", response_model=UniverseBacktestResultDTO)
async def run_universe_golden_cross_backtest(
    request: UniverseBacktestRequestDTO,
    session: DatabaseSession,
    service: BacktestService = Depends(get_backtest_service),
    admin_access: AdminAccessDep = None,
):
    base_strategy_params = {
        # 후보 스캔(scan_golden_cross_candidates)과 동일한 config MA를 기본값으로 사용
        # (요청자가 strategy_params로 override 가능) — 후보/백테스트 MA 불일치 방지
        "short_period": settings.gc_short_ma_period,
        "long_period": settings.gc_long_ma_period,
        "stoch_k_period": 14,
        "stoch_d_period": 3,
        "stoch_oversold": 30.0,
        "stoch_overbought": 70.0,
        "require_k_above_d_for_buy": False,
        "require_k_below_d_for_sell": False,
        "buy_recovery_threshold": 45.0,
        "min_pullback_bars": 4,
        "min_reentry_cooldown_bars": 10,
        "disable_stoch_overbought_sell": True,
        "breakeven_activation": 0.06,
        "partial_take_profit_1": 0.10,
        "partial_take_profit_2": 0.16,
        "max_hold_days": 60,
    }
    if request.strategy_params:
        base_strategy_params.update(request.strategy_params)

    # strategy_params override MA 검증(자유 dict라 settings 불변식을 우회 → 여기서 방어).
    # 잘못된 값이 후보 스캔/지표 계산으로 흘러들어 후보 왜곡·0건을 유발하지 않게 한다.
    try:
        _short_ma = int(base_strategy_params["short_period"])
        _long_ma = int(base_strategy_params["long_period"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(
            status_code=422,
            detail="strategy_params.short_period/long_period는 정수여야 합니다.",
        )
    if _short_ma <= 0 or _long_ma <= 0 or _short_ma >= _long_ma:
        raise HTTPException(
            status_code=422,
            detail=(
                "MA 기간이 유효하지 않습니다: 0 < short_period < long_period 이어야 합니다 "
                f"(short={_short_ma}, long={_long_ma})."
            ),
        )
    # 정규화한 정수를 dict에 되써서 후보 스캔과 백테스트 엔진이 동일한 정수 MA를 쓰게 함
    # ("20"/20.9 같은 값이 스캔은 int, 엔진은 원본으로 흘러 불일치/타입오류가 나지 않도록)
    base_strategy_params["short_period"] = _short_ma
    base_strategy_params["long_period"] = _long_ma

    symbols, selection_method = await _select_universe_symbols(
        request, session, base_strategy_params, _short_ma, _long_ma
    )

    if not symbols:
        diagnostic_summary = service.summarize_multi_symbol_results(
            MultiSymbolBacktestResultDTO(results={}, total_count=0, success_count=0, failed_count=0)
        )
        portfolio_summary = None
        if request.portfolio:
            portfolio_summary = service.simulate_universe_portfolio(
                MultiSymbolBacktestResultDTO(
                    results={}, total_count=0, success_count=0, failed_count=0
                ),
                request.backtest_config.initial_capital,
                request.max_positions,
            )
        return UniverseBacktestResultDTO(
            market=request.market,
            eligible_only=request.eligible_only,
            symbols=[],
            start_date=request.start_date,
            end_date=request.end_date,
            strategy_type=request.strategy_type,
            config_summary={
                "label": "공격형 중단기 스윙 매도 v3",
                "comparison_results": [],
                "selection_method": selection_method,
                "selection_note": _SELECTION_NOTE,
            },
            portfolio_summary=portfolio_summary,
            summary=diagnostic_summary,
            diagnostic_summary=diagnostic_summary,
            results={},
        )

    def build_strategy_config() -> StrategyConfigDTO:
        strategy_config = StrategyConfigDTO()
        strategy_config.risk_management.use_stop_loss = True
        strategy_config.risk_management.stop_loss_ratio = -DEFAULT_PEAK_DRAWDOWN_STOP_RATIO
        strategy_config.risk_management.use_take_profit = False
        strategy_config.risk_management.take_profit_ratio = None
        strategy_config.risk_management.use_trailing_stop = True
        strategy_config.risk_management.trailing_stop_ratio = 0.07
        strategy_config.risk_management.use_atr_stop_loss = False
        strategy_config.risk_management.use_atr_trailing_stop = False
        return strategy_config

    variant_defs = [
        (
            "baseline_v1",
            "기존형: 과매수 즉시 청산",
            {
                **base_strategy_params,
                "disable_stoch_overbought_sell": False,
                "partial_take_profit_1": 9.99,
                "partial_take_profit_2": 19.99,
            },
        ),
        (
            "no_overbought_sell",
            "개선형 1: 과매수 즉시 청산 제거",
            {
                **base_strategy_params,
                "disable_stoch_overbought_sell": True,
                "partial_take_profit_1": 9.99,
                "partial_take_profit_2": 19.99,
            },
        ),
        ("swing_v2", "개선형 2: 스윙형 부분익절/본전보호/트레일링", base_strategy_params),
    ]

    comparison_results = []
    final_multi_result = None
    final_request = None
    for key, label, strategy_params in variant_defs:
        multi_request = MultiSymbolBacktestRequestDTO(
            symbols=symbols,
            start_date=request.start_date,
            end_date=request.end_date,
            strategy_type=request.strategy_type,
            strategy_params=strategy_params,
            strategy_config=build_strategy_config(),
            backtest_config=request.backtest_config,
        )
        multi_result = await service.run_multi_symbol_backtest(multi_request)
        summary = service.summarize_multi_symbol_results(multi_result)
        comparison_results.append(
            {
                "key": key,
                "label": label,
                "summary_type": summary.summary_type,
                "diagnostic_average_return": summary.average_return,
                "diagnostic_average_win_rate": summary.average_win_rate,
                "average_holding_days": summary.average_holding_days,
                "profitable_ratio": summary.profitable_ratio,
                "total_trades": summary.total_trades,
            }
        )
        if key == "swing_v2":
            final_multi_result = multi_result
            final_request = multi_request

    assert final_multi_result is not None and final_request is not None

    config_summary = {
        "label": "공격형 중단기 스윙 매도 v3",
        "universe_count": len(symbols),
        "peak_drawdown_stop": -DEFAULT_PEAK_DRAWDOWN_STOP_RATIO,
        "breakeven_activation": base_strategy_params["breakeven_activation"],
        "partial_take_profit_1": base_strategy_params["partial_take_profit_1"],
        "partial_take_profit_2": base_strategy_params["partial_take_profit_2"],
        "trailing_stop": 0.07,
        "max_hold_days": base_strategy_params["max_hold_days"],
        "entry_strategy": "golden_cross_recovery_pullback",
        "entry_params": base_strategy_params,
        "comparison_results": comparison_results,
        "selection_method": selection_method,
        "selection_note": _SELECTION_NOTE,
    }

    return service.build_universe_backtest_result(
        market=request.market,
        eligible_only=request.eligible_only,
        symbols=symbols,
        request=final_request,
        multi_result=final_multi_result,
        config_summary=config_summary,
        portfolio_enabled=request.portfolio,
        max_positions=request.max_positions,
    )


@router.get("/universe/golden-cross", response_model=UniverseBacktestResultDTO)
async def get_universe_golden_cross_backtest(
    session: DatabaseSession,
    service: BacktestService = Depends(get_backtest_service),
    admin_access: AdminAccessDep = None,
    market: str | None = Query(default=None),
    eligible_only: bool = Query(default=True),
    limit: int = Query(default=20, ge=1, le=100),
    start_date: date = Query(...),
    end_date: date = Query(...),
    portfolio: bool = Query(default=False),
    max_positions: int = Query(default=5, ge=1, le=100),
    execution_timing: ExecutionTiming = Query(default="next_open"),
    cost_schedule_date: date | None = Query(default=None),
    commission_rate: float | None = Query(default=None, ge=0.0, le=0.01),
    tax_rate: float | None = Query(default=None, ge=0.0, le=0.01),
    slippage_rate: float | None = Query(default=None, ge=0.0, le=0.01),
):
    backtest_config = BacktestConfigDTO(
        execution_timing=execution_timing,
        cost_schedule_date=cost_schedule_date,
        commission_rate=commission_rate,
        tax_rate=tax_rate,
        slippage_rate=slippage_rate,
    )
    request = UniverseBacktestRequestDTO(
        market=market,
        eligible_only=eligible_only,
        limit=limit,
        start_date=datetime.combine(start_date, time.min),
        end_date=datetime.combine(end_date, time.min),
        portfolio=portfolio,
        max_positions=max_positions,
        backtest_config=backtest_config,
    )
    return await run_universe_golden_cross_backtest(request, session, service, admin_access)


@router.post("/validate-data")
async def validate_data_quality(
    symbol: str,
    start_date: date = Query(..., description="시작일 (YYYY-MM-DD)"),
    end_date: date = Query(..., description="종료일 (YYYY-MM-DD)"),
    service: BacktestService = Depends(get_backtest_service),
    admin_access: AdminAccessDep = None,
):
    start_dt = datetime.combine(start_date, time.min)
    end_dt = datetime.combine(end_date, time.min)
    return await service.validate_data_quality(symbol, start_dt, end_dt)


@router.get("/walk-forward/latest", response_model=WalkForwardReportDTO)
async def get_latest_walk_forward_report(
    admin_access: AdminAccessDep = None,
) -> WalkForwardReportDTO:
    """저장된 최신 walk-forward 검증 리포트를 read-only로 반환한다.

    실행은 컨테이너 CLI(`scripts/run_walk_forward.py`)에서만 이뤄지며, 이 엔드포인트는
    `reports/walk_forward_*.json` 최신 산출물만 읽어 노출한다. 리포트가 없으면
    `available=False`로 200 응답한다.
    """
    return WalkForwardReportReader().load_latest()


@router.get("/health")
async def health_check():
    return {"status": "healthy", "service": "backtest", "version": "1.0.0"}
