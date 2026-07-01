# -*- coding: utf-8 -*-
"""
RecommendationScanService 테스트

가치주 스크리너 + 골든크로스 스캔 결과 병합 로직 검증.
두 서비스의 실제 구현은 모두 스텁으로 대체한다(외부 API/DB 미사용).
"""

from datetime import datetime
from decimal import Decimal

import pytest

import src.application.domain.recommendation.recommendation_scan_service as scan_service_module
from src.application.common.exceptions import ResourceNotFoundError
from src.application.domain.recommendation.dto import ReadinessLabel, RecommendationRuleCandidateDTO
from src.application.domain.recommendation.recommendation_scan_service import (
    RecommendationScanService,
)
from src.application.domain.recommendation.rule_set_mapper import candidates_to_json
from src.application.domain.screener.dto import ValueScreenerResultDTO, ValueStockItemDTO
from src.application.domain.strategy.dto import GoldenCrossScanItemDTO, GoldenCrossScanListDTO


class _FakeRuleSetModel:
    def __init__(self, id, name, version, status, candidates_json, frozen_hash):  # noqa: A002
        self.id = id
        self.name = name
        self.version = version
        self.status = status
        self.candidates_json = candidates_json
        self.frozen_hash = frozen_hash


class _StubRuleSetRepository:
    def __init__(self, model=None) -> None:
        self._model = model

    async def get_active_by_id(self, rule_set_id, session=None):
        _ = rule_set_id, session
        return self._model


def _gc_item(symbol: str, gc_state: str) -> GoldenCrossScanItemDTO:
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
    )


def _value_item(symbol: str) -> ValueStockItemDTO:
    return ValueStockItemDTO(
        symbol=symbol,
        name=f"종목{symbol}",
        market_cap=500_000_000_000,
        market_cap_display="5000억",
        retention_ratio=800.0,
        quick_ratio=150.0,
        debt_ratio=40.0,
    )


class _StubBuyStrategyService:
    def __init__(
        self,
        stocks: list[GoldenCrossScanItemDTO],
        errors: list[str] | None = None,
        captured_calls: list[tuple] | None = None,
    ) -> None:
        self._stocks = stocks
        self._errors = errors or []
        self._captured_calls = captured_calls

    async def scan_golden_cross_candidates(self, *args, **kwargs):
        if self._captured_calls is not None:
            self._captured_calls.append((args, kwargs))
        return GoldenCrossScanListDTO(
            stocks=self._stocks,
            total_scanned=len(self._stocks),
            gc_active_count=len(self._stocks),
            pullback_waiting_count=0,
            ready_to_buy_count=0,
            scan_time=datetime(2026, 7, 1, 9, 0, 0),
            errors=self._errors,
        )


class _StubValueScreenerService:
    def __init__(self, items: list[ValueStockItemDTO]) -> None:
        self._items = items

    async def screen_stocks(self, criteria, symbols=None, **kwargs):
        _ = criteria, kwargs
        items = [item for item in self._items if symbols is None or item.symbol in symbols]
        return ValueScreenerResultDTO(
            items=items,
            total_count=len(items),
            filtered_count=len(items),
            criteria=criteria,
        )


@pytest.mark.asyncio
async def test_merge_includes_candidate_with_both_technical_and_fundamental_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gc_stocks = [_gc_item("005930", "OPTIMAL_BUY")]
    value_items = [_value_item("005930")]

    monkeypatch.setattr(
        scan_service_module,
        "BuyStrategyService",
        lambda **kwargs: _StubBuyStrategyService(gc_stocks),
    )
    monkeypatch.setattr(
        scan_service_module,
        "ValueScreenerService",
        lambda *args, **kwargs: _StubValueScreenerService(value_items),
    )

    service = RecommendationScanService(naver_client=object(), session=object())
    result = await service.scan_candidates()

    assert result.candidate_count == 1
    candidate = result.candidates[0]
    assert candidate.symbol == "005930"
    assert candidate.has_fundamental_evidence is True
    assert candidate.readiness_label == ReadinessLabel.RESEARCH


@pytest.mark.asyncio
async def test_merge_keeps_candidate_without_matching_fundamental_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gc_stocks = [_gc_item("000660", "BUY_INTEREST")]

    monkeypatch.setattr(
        scan_service_module,
        "BuyStrategyService",
        lambda **kwargs: _StubBuyStrategyService(gc_stocks),
    )
    monkeypatch.setattr(
        scan_service_module,
        "ValueScreenerService",
        lambda *args, **kwargs: _StubValueScreenerService([]),
    )

    service = RecommendationScanService(naver_client=object(), session=object())
    result = await service.scan_candidates()

    assert result.candidate_count == 1
    candidate = result.candidates[0]
    assert candidate.symbol == "000660"
    assert candidate.has_fundamental_evidence is False
    assert candidate.scorecard.fundamental_score is None
    assert "fundamental_review" in candidate.missing_evidence


@pytest.mark.asyncio
async def test_no_golden_cross_candidates_skips_value_screener_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class _CountingValueScreenerService:
        def __init__(self, *args, **kwargs):
            calls.append("constructed")

    monkeypatch.setattr(
        scan_service_module,
        "BuyStrategyService",
        lambda **kwargs: _StubBuyStrategyService([]),
    )
    monkeypatch.setattr(scan_service_module, "ValueScreenerService", _CountingValueScreenerService)

    service = RecommendationScanService(naver_client=object(), session=object())
    result = await service.scan_candidates()

    assert result.candidate_count == 0
    assert calls == []


@pytest.mark.asyncio
async def test_reuses_request_session_for_golden_cross_scan_instead_of_opening_a_new_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_calls: list[tuple] = []
    request_session = object()

    monkeypatch.setattr(
        scan_service_module,
        "BuyStrategyService",
        lambda **kwargs: _StubBuyStrategyService([], captured_calls=captured_calls),
    )
    monkeypatch.setattr(
        scan_service_module,
        "ValueScreenerService",
        lambda *args, **kwargs: _StubValueScreenerService([]),
    )

    service = RecommendationScanService(naver_client=object(), session=request_session)
    await service.scan_candidates()

    assert len(captured_calls) == 1
    args, _ = captured_calls[0]
    assert args == (request_session,)


@pytest.mark.asyncio
async def test_golden_cross_scan_errors_are_propagated_to_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        scan_service_module,
        "BuyStrategyService",
        lambda **kwargs: _StubBuyStrategyService([], errors=["005930: OHLCV load failed"]),
    )
    monkeypatch.setattr(
        scan_service_module,
        "ValueScreenerService",
        lambda *args, **kwargs: _StubValueScreenerService([]),
    )

    service = RecommendationScanService(naver_client=object(), session=object())
    result = await service.scan_candidates()

    assert result.errors == ["005930: OHLCV load failed"]


@pytest.mark.asyncio
async def test_rule_set_id_overrides_stoch_threshold_with_frozen_candidate_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_calls: list[tuple] = []
    candidate = RecommendationRuleCandidateDTO(
        candidate_id="c1", name="baseline", rules={"stoch_oversold": 22.5, "short_period": 20}
    )
    model = _FakeRuleSetModel(
        id=1,
        name="rs",
        version=1,
        status="active",
        candidates_json=candidates_to_json([candidate]),
        frozen_hash=None,
    )

    monkeypatch.setattr(
        scan_service_module,
        "RecommendationRuleSetRepository",
        lambda: _StubRuleSetRepository(model),
    )
    monkeypatch.setattr(
        scan_service_module,
        "BuyStrategyService",
        lambda **kwargs: _StubBuyStrategyService([], captured_calls=captured_calls),
    )
    monkeypatch.setattr(
        scan_service_module,
        "ValueScreenerService",
        lambda *args, **kwargs: _StubValueScreenerService([]),
    )

    service = RecommendationScanService(naver_client=object(), session=object())
    await service.scan_candidates(stoch_threshold=30.0, rule_set_id="1")

    assert len(captured_calls) == 1
    _, kwargs = captured_calls[0]
    assert kwargs["stoch_threshold"] == 22.5


@pytest.mark.asyncio
async def test_rule_set_id_selects_candidate_matching_frozen_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_calls: list[tuple] = []
    losing_candidate = RecommendationRuleCandidateDTO(
        candidate_id="c-slow", name="slow", rules={"stoch_oversold": 30.0}
    )
    winning_candidate = RecommendationRuleCandidateDTO(
        candidate_id="c-fast", name="fast", rules={"stoch_oversold": 20.0}
    )
    model = _FakeRuleSetModel(
        id=2,
        name="rs",
        version=1,
        status="active",
        candidates_json=candidates_to_json([losing_candidate, winning_candidate]),
        frozen_hash=winning_candidate.frozen_hash,
    )

    monkeypatch.setattr(
        scan_service_module,
        "RecommendationRuleSetRepository",
        lambda: _StubRuleSetRepository(model),
    )
    monkeypatch.setattr(
        scan_service_module,
        "BuyStrategyService",
        lambda **kwargs: _StubBuyStrategyService([], captured_calls=captured_calls),
    )
    monkeypatch.setattr(
        scan_service_module,
        "ValueScreenerService",
        lambda *args, **kwargs: _StubValueScreenerService([]),
    )

    service = RecommendationScanService(naver_client=object(), session=object())
    await service.scan_candidates(rule_set_id="2")

    _, kwargs = captured_calls[0]
    assert kwargs["stoch_threshold"] == 20.0


@pytest.mark.asyncio
async def test_rule_set_id_raises_resource_not_found_when_no_active_rule_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        scan_service_module, "RecommendationRuleSetRepository", lambda: _StubRuleSetRepository(None)
    )

    service = RecommendationScanService(naver_client=object(), session=object())

    with pytest.raises(ResourceNotFoundError):
        await service.scan_candidates(rule_set_id="999")


@pytest.mark.asyncio
async def test_scan_without_rule_set_id_keeps_phase1_default_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """rule_set_id 미지정 시 RecommendationRuleSetRepository는 전혀 호출되지 않아야 한다."""
    calls: list[str] = []

    class _CountingRepository:
        def __init__(self) -> None:
            calls.append("constructed")

    monkeypatch.setattr(scan_service_module, "RecommendationRuleSetRepository", _CountingRepository)
    monkeypatch.setattr(
        scan_service_module, "BuyStrategyService", lambda **kwargs: _StubBuyStrategyService([])
    )
    monkeypatch.setattr(
        scan_service_module,
        "ValueScreenerService",
        lambda *args, **kwargs: _StubValueScreenerService([]),
    )

    service = RecommendationScanService(naver_client=object(), session=object())
    await service.scan_candidates(stoch_threshold=30.0)

    assert calls == []
