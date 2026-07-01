# -*- coding: utf-8 -*-
"""
RecommendationRuleSetService 테스트

실제 DB(로컬 docker postgres)를 사용한다. @transaction은 session이 첫 번째
positional 인자로 이미 전달되면 자동 커밋을 건너뛰므로, 여기서는 session을
명시적으로 넘겨 rollback 기반 fixture로 데이터를 남기지 않는다.
"""

import json
from datetime import date, datetime
from decimal import Decimal

import pandas as pd
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import src.application.domain.recommendation.rule_set_validation_service as validation_service_module
from src.adapters.database.connection import AsyncSessionLocal, engine
from src.adapters.database.repositories.recommendation_rule_set_repository import (
    RecommendationRuleValidationRepository,
)
from src.application.common.exceptions import (
    InvalidInputError,
    ResourceNotFoundError,
    ValidationError,
)
from src.application.domain.backtest.dto import (
    BacktestResultDTO,
    MultiSymbolBacktestResultDTO,
)
from src.application.domain.recommendation.dto import (
    RecommendationRuleCandidateDTO,
    RecommendationRuleSetCreateRequestDTO,
    RecommendationRuleSetValidationRequestDTO,
    RuleSetStatus,
)
from src.application.domain.recommendation.rule_set_service import RecommendationRuleSetService
from src.application.domain.strategy.dto import GoldenCrossScanItemDTO, GoldenCrossScanListDTO


@pytest.fixture
async def session():
    async with AsyncSessionLocal() as db:
        yield db
        await db.rollback()
    await engine.dispose()


def _gc_item(symbol: str) -> GoldenCrossScanItemDTO:
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
        gc_state="OPTIMAL_BUY",
        screening_score=Decimal("80"),
    )


class _StubBuyStrategyService:
    def __init__(self, session=None, universe_repo=None) -> None:
        _ = session, universe_repo

    async def scan_golden_cross_candidates(self, session, **kwargs):
        _ = session, kwargs
        return GoldenCrossScanListDTO(
            stocks=[_gc_item("005930")],
            total_scanned=1,
            gc_active_count=1,
            pullback_waiting_count=0,
            ready_to_buy_count=0,
            scan_time=datetime(2026, 7, 1, 9, 0, 0),
        )


def _backtest_result(symbol: str, cagr: float) -> BacktestResultDTO:
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
        mdd=-3.0,
        volatility=10.0,
        sharpe_ratio=1.0,
        sortino_ratio=0.0,
        calmar_ratio=0.0,
        var_95=0.0,
        total_trades=5,
        winning_trades=3,
        losing_trades=2,
        win_rate=60.0,
        profit_factor=1.5,
        avg_win=2.0,
        avg_loss=-1.0,
        avg_win_loss_ratio=2.0,
        avg_holding_days=5.0,
        max_consecutive_wins=2,
        max_consecutive_losses=1,
    )


class _StubDataLoader:
    async def load_ohlcv_data(self, symbol, start_date, end_date, **kwargs):
        _ = symbol, kwargs
        return pd.DataFrame({"close": [10000.0, 11000.0]}), start_date, end_date


class _StubBacktestService:
    def __init__(self) -> None:
        self.data_loader = _StubDataLoader()

    async def run_multi_symbol_backtest(self, request):
        results = {symbol: _backtest_result(symbol, cagr=12.0) for symbol in request.symbols}
        return MultiSymbolBacktestResultDTO(
            results=results,
            total_count=len(request.symbols),
            success_count=len(request.symbols),
            failed_count=0,
        )


@pytest.mark.asyncio
async def test_create_rule_set_persists_draft_with_candidates(session: AsyncSession) -> None:
    service = RecommendationRuleSetService()
    request = RecommendationRuleSetCreateRequestDTO(
        name="golden-cross-swing",
        candidates=[
            RecommendationRuleCandidateDTO(
                candidate_id="c1", name="baseline", rules={"stoch_oversold": 30.0}
            )
        ],
    )

    created = await service.create_rule_set(session, request)

    assert created.status == RuleSetStatus.DRAFT
    assert created.frozen_hash is None
    assert created.candidates[0].candidate_id == "c1"
    assert created.rule_id


@pytest.mark.asyncio
async def test_list_rule_sets_returns_created_rule_set(session: AsyncSession) -> None:
    service = RecommendationRuleSetService()
    request = RecommendationRuleSetCreateRequestDTO(
        name="rs-list-test",
        candidates=[
            RecommendationRuleCandidateDTO(
                candidate_id="c1", name="c1", rules={"stoch_oversold": 30.0}
            )
        ],
    )
    created = await service.create_rule_set(session, request)

    result = await service.list_rule_sets(session)

    assert any(rule_set.rule_id == created.rule_id for rule_set in result.rule_sets)


@pytest.mark.asyncio
async def test_validate_rule_set_activates_and_persists_validation(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(validation_service_module, "BuyStrategyService", _StubBuyStrategyService)

    service = RecommendationRuleSetService()
    create_request = RecommendationRuleSetCreateRequestDTO(
        name="rs-validate-test",
        candidates=[
            RecommendationRuleCandidateDTO(
                candidate_id="c1", name="c1", rules={"stoch_oversold": 30.0, "short_period": 20}
            )
        ],
    )
    created = await service.create_rule_set(session, create_request)

    validate_request = RecommendationRuleSetValidationRequestDTO(
        train_start=date(2024, 1, 1),
        train_end=date(2024, 6, 30),
        test_start=date(2024, 7, 1),
        test_end=date(2024, 12, 31),
        benchmark="0001",
    )

    result = await service.validate_rule_set(
        session, created.rule_id, validate_request, _StubBacktestService()
    )

    assert result.selected_candidate_id == "c1"
    assert result.selected_candidate_hash

    listed = await service.list_rule_sets(session)
    updated_rule_set = next(rs for rs in listed.rule_sets if rs.rule_id == created.rule_id)
    assert updated_rule_set.status == RuleSetStatus.ACTIVE
    assert updated_rule_set.frozen_hash == result.selected_candidate_hash

    # 실제로 recommendation_rule_validations에 정확한 값이 저장됐는지 직접 확인한다
    # (매핑이 뒤바뀌거나 빈 JSON이 저장돼도 서비스 반환값만 보면 통과할 수 있으므로).
    validation_repo = RecommendationRuleValidationRepository()
    persisted = await validation_repo.get_latest_by_rule_set_id(
        int(created.rule_id), session=session
    )
    assert persisted is not None
    assert persisted.selected_candidate_id == "c1"
    assert persisted.selected_candidate_hash == result.selected_candidate_hash
    assert persisted.benchmark == "0001"
    assert persisted.selection_metric == "cagr"
    assert persisted.train_start == date(2024, 1, 1)
    assert persisted.test_end == date(2024, 12, 31)
    assert json.loads(persisted.train_metrics_json)["cagr"] == result.train_metrics.cagr
    assert json.loads(persisted.test_metrics_json)["cagr"] == result.test_metrics.cagr


@pytest.mark.asyncio
async def test_validate_rule_set_raises_when_rule_set_not_found(session: AsyncSession) -> None:
    service = RecommendationRuleSetService()
    validate_request = RecommendationRuleSetValidationRequestDTO(
        train_start=date(2024, 1, 1),
        train_end=date(2024, 6, 30),
        test_start=date(2024, 7, 1),
        test_end=date(2024, 12, 31),
        benchmark="0001",
    )

    with pytest.raises(ResourceNotFoundError):
        await service.validate_rule_set(session, "999999", validate_request, _StubBacktestService())


@pytest.mark.asyncio
async def test_validate_rule_set_raises_invalid_input_for_non_numeric_rule_id(
    session: AsyncSession,
) -> None:
    service = RecommendationRuleSetService()
    validate_request = RecommendationRuleSetValidationRequestDTO(
        train_start=date(2024, 1, 1),
        train_end=date(2024, 6, 30),
        test_start=date(2024, 7, 1),
        test_end=date(2024, 12, 31),
        benchmark="0001",
    )

    with pytest.raises(InvalidInputError):
        await service.validate_rule_set(
            session, "not-a-number", validate_request, _StubBacktestService()
        )


@pytest.mark.asyncio
async def test_validate_rule_set_raises_and_does_not_activate_when_universe_is_empty(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
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

    monkeypatch.setattr(
        validation_service_module, "BuyStrategyService", _EmptyUniverseBuyStrategyService
    )

    service = RecommendationRuleSetService()
    create_request = RecommendationRuleSetCreateRequestDTO(
        name="rs-empty-universe",
        candidates=[
            RecommendationRuleCandidateDTO(
                candidate_id="c1", name="c1", rules={"stoch_oversold": 30.0}
            )
        ],
    )
    created = await service.create_rule_set(session, create_request)

    validate_request = RecommendationRuleSetValidationRequestDTO(
        train_start=date(2024, 1, 1),
        train_end=date(2024, 6, 30),
        test_start=date(2024, 7, 1),
        test_end=date(2024, 12, 31),
        benchmark="0001",
    )

    # RecommendationRuleSetService는 WalkForwardValidationError(ApplicationError 아님 ->
    # 전역 핸들러가 500으로 반환)를 ValidationError(400)로 변환해야 한다.
    with pytest.raises(ValidationError):
        await service.validate_rule_set(
            session, created.rule_id, validate_request, _StubBacktestService()
        )

    listed = await service.list_rule_sets(session)
    unchanged_rule_set = next(rs for rs in listed.rule_sets if rs.rule_id == created.rule_id)
    assert unchanged_rule_set.status == RuleSetStatus.DRAFT
    assert unchanged_rule_set.frozen_hash is None


@pytest.mark.asyncio
async def test_create_rule_set_increments_version_on_same_name_reregistration(
    session: AsyncSession,
) -> None:
    service = RecommendationRuleSetService()
    request = RecommendationRuleSetCreateRequestDTO(
        name="rs-versioned",
        candidates=[
            RecommendationRuleCandidateDTO(
                candidate_id="c1", name="c1", rules={"stoch_oversold": 30.0}
            )
        ],
    )

    first = await service.create_rule_set(session, request)
    second = await service.create_rule_set(session, request)

    assert first.version == 1
    assert second.version == 2


@pytest.mark.asyncio
async def test_list_rule_sets_total_count_reflects_full_db_count_not_page_size(
    session: AsyncSession,
) -> None:
    service = RecommendationRuleSetService()
    for i in range(3):
        await service.create_rule_set(
            session,
            RecommendationRuleSetCreateRequestDTO(
                name=f"rs-page-{i}",
                candidates=[
                    RecommendationRuleCandidateDTO(
                        candidate_id="c1", name="c1", rules={"stoch_oversold": 30.0}
                    )
                ],
            ),
        )

    result = await service.list_rule_sets(session, limit=1, offset=0)

    assert len(result.rule_sets) == 1
    assert result.total_count >= 3
