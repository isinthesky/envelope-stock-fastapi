# -*- coding: utf-8 -*-
"""
Backtest Router - 백테스팅 API 엔드포인트
"""

from datetime import date, datetime, time

from fastapi import APIRouter, Depends, Query

from src.application.common.dependencies import DatabaseSession, get_kis_client, get_redis_client
from src.application.domain.backtest.dto import BacktestRequestDTO, BacktestResultDTO, MultiSymbolBacktestRequestDTO, MultiSymbolBacktestResultDTO, UniverseBacktestRequestDTO, UniverseBacktestResultDTO
from src.application.domain.backtest.service import BacktestService
from src.application.domain.market_data.service import MarketDataService
from src.application.domain.strategy.buy_strategy_service import BuyStrategyService
from src.application.domain.strategy.dto import StrategyConfigDTO

router = APIRouter(prefix="/api/v1/backtest", tags=["Backtest"])


async def get_backtest_service(session: DatabaseSession, kis_client=Depends(get_kis_client), redis_client=Depends(get_redis_client)) -> BacktestService:
    market_data_service = MarketDataService(kis_client, redis_client)
    return BacktestService(market_data_service, db_session=session)


@router.post("/run", response_model=BacktestResultDTO)
async def run_backtest(request: BacktestRequestDTO, service: BacktestService = Depends(get_backtest_service)):
    return await service.run_backtest(request)


@router.post("/run-multi", response_model=MultiSymbolBacktestResultDTO)
async def run_multi_symbol_backtest(request: MultiSymbolBacktestRequestDTO, service: BacktestService = Depends(get_backtest_service)):
    return await service.run_multi_symbol_backtest(request)


@router.post("/run-universe-golden-cross", response_model=UniverseBacktestResultDTO)
async def run_universe_golden_cross_backtest(request: UniverseBacktestRequestDTO, session: DatabaseSession, service: BacktestService = Depends(get_backtest_service)):
    base_strategy_params = {
        "short_period": 55,
        "long_period": 165,
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

    buy_service = BuyStrategyService(session=session)
    scan = await buy_service.scan_golden_cross_candidates(
        market=request.market,
        stoch_threshold=float(base_strategy_params.get("stoch_oversold", 30.0)),
        gc_only=False,
        include_etf=False,
        limit=max(request.limit * 5, request.limit),
    )

    preferred_states = ["OPTIMAL_BUY", "READY_TO_BUY", "BUY_INTEREST", "WAITING_FOR_PULLBACK"]
    selected_scan_items = [item for state in preferred_states for item in scan.stocks if item.gc_state == state]
    if request.eligible_only:
        selected_scan_items = [item for item in selected_scan_items if item.screening_score is not None]

    symbols, seen_symbols = [], set()
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
            config_summary={"label": "공격형 중단기 스윙 매도 v3", "comparison_results": []},
            summary=service.summarize_multi_symbol_results(MultiSymbolBacktestResultDTO(results={}, total_count=0, success_count=0, failed_count=0)),
            results={},
        )

    def build_strategy_config() -> StrategyConfigDTO:
        strategy_config = StrategyConfigDTO()
        strategy_config.risk_management.use_stop_loss = True
        strategy_config.risk_management.stop_loss_ratio = -0.05
        strategy_config.risk_management.use_take_profit = False
        strategy_config.risk_management.take_profit_ratio = None
        strategy_config.risk_management.use_trailing_stop = True
        strategy_config.risk_management.trailing_stop_ratio = 0.07
        strategy_config.risk_management.use_atr_stop_loss = False
        strategy_config.risk_management.use_atr_trailing_stop = False
        return strategy_config

    variant_defs = [
        ("baseline_v1", "기존형: 과매수 즉시 청산", {**base_strategy_params, "disable_stoch_overbought_sell": False, "partial_take_profit_1": 9.99, "partial_take_profit_2": 19.99}),
        ("no_overbought_sell", "개선형 1: 과매수 즉시 청산 제거", {**base_strategy_params, "disable_stoch_overbought_sell": True, "partial_take_profit_1": 9.99, "partial_take_profit_2": 19.99}),
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
        comparison_results.append({
            "key": key,
            "label": label,
            "average_return": summary.average_return,
            "average_win_rate": summary.average_win_rate,
            "average_holding_days": summary.average_holding_days,
            "profitable_ratio": summary.profitable_ratio,
            "total_trades": summary.total_trades,
        })
        if key == "swing_v2":
            final_multi_result = multi_result
            final_request = multi_request

    assert final_multi_result is not None and final_request is not None

    config_summary = {
        "label": "공격형 중단기 스윙 매도 v3",
        "universe_count": len(symbols),
        "stop_loss": -0.05,
        "breakeven_activation": base_strategy_params["breakeven_activation"],
        "partial_take_profit_1": base_strategy_params["partial_take_profit_1"],
        "partial_take_profit_2": base_strategy_params["partial_take_profit_2"],
        "trailing_stop": 0.07,
        "max_hold_days": base_strategy_params["max_hold_days"],
        "entry_strategy": "golden_cross_recovery_pullback",
        "entry_params": base_strategy_params,
        "comparison_results": comparison_results,
    }

    return service.build_universe_backtest_result(market=request.market, eligible_only=request.eligible_only, symbols=symbols, request=final_request, multi_result=final_multi_result, config_summary=config_summary)


@router.post("/validate-data")
async def validate_data_quality(symbol: str, start_date: date = Query(..., description="시작일 (YYYY-MM-DD)"), end_date: date = Query(..., description="종료일 (YYYY-MM-DD)"), service: BacktestService = Depends(get_backtest_service)):
    start_dt = datetime.combine(start_date, time.min)
    end_dt = datetime.combine(end_date, time.min)
    return await service.validate_data_quality(symbol, start_dt, end_dt)


@router.get("/health")
async def health_check():
    return {"status": "healthy", "service": "backtest", "version": "1.0.0"}
