# -*- coding: utf-8 -*-
"""
RecommendationRuleSetValidationService 테스트

BuyStrategyService(유니버스 선정)와 BacktestService(train/test 백테스트 실행)를
모두 스텁으로 대체해, walk-forward 엔진(WalkForwardValidationRunner) 연동
자체("이미 있는 미사용 엔진을 처음으로 실제로 호출한다")를 검증한다.
"""

from datetime import date, datetime
from decimal import Decimal

import pandas as pd
import pytest

import src.application.domain.recommendation.rule_set_validation_service as validation_service_module
from src.application.domain.backtest.dto import (
    BacktestResultDTO,
    MultiSymbolBacktestResultDTO,
)
from src.application.domain.backtest.validation import WalkForwardValidationError
from src.application.domain.recommendation.dto import (
    RecommendationRuleCandidateDTO,
    RecommendationRuleSetDTO,
)
from src.application.domain.recommendation.rule_set_validation_service import (
    RecommendationRuleSetValidationService,
)
from src.application.domain.strategy.dto import GoldenCrossScanItemDTO, GoldenCrossScanListDTO


def _gc_item(symbol: str, gc_state: str = "OPTIMAL_BUY") -> GoldenCrossScanItemDTO:
    return GoldenCrossScanItemDTO(
        symbol=symbol,
        name=f"종목{symbol}",
        market="KOSPI",
        current_price=Decimal("10000"),
        ma_short=Decimal("9500"),
        ma_long=Decimal("9000"),
        ma_gap_ratio=5.0,
        stoch_k=20.0,
        stoch_d=25.0,
        is_gc_active=True,
        gc_state=gc_state,
        screening_score=Decimal("80"),
    )


def _backtest_result(
    symbol: str, cagr: float, mdd: float, sharpe: float, total_trades: int
) -> BacktestResultDTO:
    return BacktestResultDTO(
        symbol=symbol,
        start_date=datetime(2024, 1, 1),
        end_date=datetime(2024, 6, 30),
        initial_capital=Decimal("10000000"),
        final_capital=Decimal("11000000"),
        execution_timing="next_open",
        total_return=10.0,
        annualized_return=10.0,
        cagr=cagr,
        mdd=mdd,
        volatility=10.0,
        sharpe_ratio=sharpe,
        sortino_ratio=0.0,
        calmar_ratio=0.0,
        var_95=0.0,
        total_trades=total_trades,
        winning_trades=1,
        losing_trades=0,
        win_rate=100.0,
        profit_factor=1.0,
        avg_win=1.0,
        avg_loss=0.0,
        avg_win_loss_ratio=1.0,
        avg_holding_days=5.0,
        max_consecutive_wins=1,
        max_consecutive_losses=0,
    )


class _StubBuyStrategyService:
    def __init__(self, session=None, universe_repo=None) -> None:
        _ = session, universe_repo

    async def scan_golden_cross_candidates(self, session, **kwargs):
        _ = session, kwargs
        return GoldenCrossScanListDTO(
            stocks=[_gc_item("005930"), _gc_item("000660")],
            total_scanned=2,
            gc_active_count=2,
            pullback_waiting_count=0,
            ready_to_buy_count=0,
            scan_time=datetime(2026, 7, 1, 9, 0, 0),
        )


class _StubDataLoader:
    """벤치마크 심볼의 시작가/종가가 항상 10000 -> 11000이 되도록 고정한다."""

    async def load_ohlcv_data(self, symbol, start_date, end_date, **kwargs):
        _ = symbol, kwargs
        data = pd.DataFrame({"close": [10000.0, 11000.0]})
        return data, start_date, end_date


class _StubBacktestService:
    """short_period 값으로 후보를 구분해 서로 다른 cagr/mdd/sharpe를 반환한다."""

    def __init__(self, metrics_by_short_period: dict[int, tuple[float, float, float, int]]) -> None:
        self.data_loader = _StubDataLoader()
        self._metrics_by_short_period = metrics_by_short_period
        self.calls: list[dict] = []

    async def run_multi_symbol_backtest(self, request):
        self.calls.append({"symbols": request.symbols, "strategy_params": request.strategy_params})
        cagr, mdd, sharpe, total_trades = self._metrics_by_short_period[
            request.strategy_params["short_period"]
        ]
        results = {
            symbol: _backtest_result(symbol, cagr, mdd, sharpe, total_trades)
            for symbol in request.symbols
        }
        return MultiSymbolBacktestResultDTO(
            results=results,
            total_count=len(request.symbols),
            success_count=len(request.symbols),
            failed_count=0,
        )


def _rule_set() -> RecommendationRuleSetDTO:
    return RecommendationRuleSetDTO(
        rule_id="rs-1",
        name="golden-cross-swing",
        candidates=[
            RecommendationRuleCandidateDTO(
                candidate_id="c-fast", name="fast", rules={"short_period": 20, "long_period": 60}
            ),
            RecommendationRuleCandidateDTO(
                candidate_id="c-slow", name="slow", rules={"short_period": 55, "long_period": 165}
            ),
        ],
    )


@pytest.mark.asyncio
async def test_validate_selects_higher_train_cagr_candidate_and_flags_data_snooping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(validation_service_module, "BuyStrategyService", _StubBuyStrategyService)

    backtest_service = _StubBacktestService(
        metrics_by_short_period={
            20: (15.0, -5.0, 1.2, 10),  # c-fast: 더 높은 CAGR
            55: (8.0, -3.0, 0.8, 4),  # c-slow
        }
    )
    service = RecommendationRuleSetValidationService(backtest_service, session=object())

    result = await service.validate(
        rule_set=_rule_set(),
        train_start=date(2024, 1, 1),
        train_end=date(2024, 6, 30),
        test_start=date(2024, 7, 1),
        test_end=date(2024, 12, 31),
        benchmark="0001",
    )

    assert result.selected_candidate.candidate_id == "c-fast"
    assert result.selected_candidate_hash
    assert "Data-Snooping Warning" in result.to_markdown()
    # 4번 호출: 후보 2개 x (train, test) 2개 윈도우
    assert len(backtest_service.calls) == 4


@pytest.mark.asyncio
async def test_validate_computes_benchmark_cagr_from_ohlcv_start_end_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(validation_service_module, "BuyStrategyService", _StubBuyStrategyService)

    backtest_service = _StubBacktestService(
        metrics_by_short_period={20: (10.0, -1.0, 1.0, 1), 55: (10.0, -1.0, 1.0, 1)}
    )
    service = RecommendationRuleSetValidationService(backtest_service, session=object())

    result = await service.validate(
        rule_set=_rule_set(),
        train_start=date(2024, 1, 1),
        train_end=date(2024, 6, 30),
        test_start=date(2024, 7, 1),
        test_end=date(2024, 12, 31),
        benchmark="0001",
    )

    # 스텁 데이터로더는 10000 -> 11000 고정이므로 benchmark_cagr > 0이어야 한다.
    assert result.selected_candidate.train_metrics.benchmark_cagr > 0
    assert result.selected_candidate.test_metrics.benchmark_cagr > 0


@pytest.mark.asyncio
async def test_validate_raises_when_train_and_test_windows_overlap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(validation_service_module, "BuyStrategyService", _StubBuyStrategyService)

    backtest_service = _StubBacktestService(
        metrics_by_short_period={20: (10.0, -1.0, 1.0, 1), 55: (10.0, -1.0, 1.0, 1)}
    )
    service = RecommendationRuleSetValidationService(backtest_service, session=object())

    with pytest.raises(WalkForwardValidationError):
        await service.validate(
            rule_set=_rule_set(),
            train_start=date(2024, 1, 1),
            train_end=date(2024, 7, 1),
            test_start=date(2024, 6, 1),
            test_end=date(2024, 12, 31),
            benchmark="0001",
        )

    # 기간 검증에서 즉시 실패해야 하며 백테스트가 실행되면 안 된다.
    assert backtest_service.calls == []


class _EmptyUniverseBuyStrategyService:
    def __init__(self, session=None, universe_repo=None) -> None:
        _ = session, universe_repo

    async def scan_golden_cross_candidates(self, session, **kwargs):
        _ = session, kwargs
        return GoldenCrossScanListDTO(
            stocks=[],
            total_scanned=0,
            gc_active_count=0,
            pullback_waiting_count=0,
            ready_to_buy_count=0,
            scan_time=datetime(2026, 7, 1, 9, 0, 0),
        )


@pytest.mark.asyncio
async def test_validate_raises_when_universe_is_empty_instead_of_scoring_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    유니버스가 비면 모든 후보가 동일한 0.0 지표를 받아 첫 후보가 그대로
    "검증 통과"로 선택돼 버릴 수 있다 - 조용히 0점 처리하는 대신 예외를 던져야 한다.
    """
    monkeypatch.setattr(
        validation_service_module, "BuyStrategyService", _EmptyUniverseBuyStrategyService
    )

    backtest_service = _StubBacktestService(
        metrics_by_short_period={20: (10.0, -1.0, 1.0, 1), 55: (10.0, -1.0, 1.0, 1)}
    )
    service = RecommendationRuleSetValidationService(backtest_service, session=object())

    with pytest.raises(WalkForwardValidationError):
        await service.validate(
            rule_set=_rule_set(),
            train_start=date(2024, 1, 1),
            train_end=date(2024, 6, 30),
            test_start=date(2024, 7, 1),
            test_end=date(2024, 12, 31),
            benchmark="0001",
        )

    assert backtest_service.calls == []


class _AllFailingBacktestService:
    """symbols는 선정되지만 모든 종목의 백테스트가 실패하는 상황을 흉내낸다."""

    def __init__(self) -> None:
        self.data_loader = _StubDataLoader()
        self.calls: list[dict] = []

    async def run_multi_symbol_backtest(self, request):
        self.calls.append({"symbols": request.symbols, "strategy_params": request.strategy_params})
        return MultiSymbolBacktestResultDTO(
            results={},
            total_count=len(request.symbols),
            success_count=0,
            failed_count=len(request.symbols),
        )


@pytest.mark.asyncio
async def test_validate_raises_when_all_backtests_fail_instead_of_scoring_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(validation_service_module, "BuyStrategyService", _StubBuyStrategyService)

    backtest_service = _AllFailingBacktestService()
    service = RecommendationRuleSetValidationService(backtest_service, session=object())

    with pytest.raises(WalkForwardValidationError):
        await service.validate(
            rule_set=_rule_set(),
            train_start=date(2024, 1, 1),
            train_end=date(2024, 6, 30),
            test_start=date(2024, 7, 1),
            test_end=date(2024, 12, 31),
            benchmark="0001",
        )
