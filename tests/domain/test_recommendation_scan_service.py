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
from src.application.domain.recommendation.dto import ReadinessLabel
from src.application.domain.recommendation.recommendation_scan_service import (
    RecommendationScanService,
)
from src.application.domain.screener.dto import ValueScreenerResultDTO, ValueStockItemDTO
from src.application.domain.strategy.dto import GoldenCrossScanItemDTO, GoldenCrossScanListDTO


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
