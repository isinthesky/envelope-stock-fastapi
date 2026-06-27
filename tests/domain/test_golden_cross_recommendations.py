from datetime import datetime
from decimal import Decimal

import pytest

from src.application.common.exceptions import StrategyError
from src.application.domain.strategy.dto import GoldenCrossScanItemDTO, GoldenCrossScanListDTO
from src.application.domain.strategy.strategy_service import StrategyService


def _stock(
    symbol: str,
    gc_state: str,
    *,
    screening_score: Decimal = Decimal("70"),
    ma_gap_ratio: float = 5.0,
    stoch_k: float = 35.0,
    stoch_d: float = 25.0,
    financial_filter_status: str | None = "PASS",
) -> GoldenCrossScanItemDTO:
    return GoldenCrossScanItemDTO(
        symbol=symbol,
        name=symbol,
        market="KOSPI",
        current_price=Decimal("10000"),
        ma_short=Decimal("105"),
        ma_long=Decimal("100"),
        ma_gap_ratio=ma_gap_ratio,
        stoch_k=stoch_k,
        stoch_d=stoch_d,
        is_gc_active=True,
        gc_state=gc_state,
        screening_score=screening_score,
        financial_filter_status=financial_filter_status,
    )


def test_recommendation_explainability_scores_and_reasons() -> None:
    service = StrategyService(session=None)
    stock = _stock("005930", "BUY_INTEREST")

    explained = service._attach_recommendation_explainability(
        stock,
        target_state_set={"OPTIMAL_BUY", "BUY_INTEREST", "READY_TO_BUY"},
        min_recommendation_score=0.0,
    )

    assert explained.recommendation_score is not None
    assert explained.recommendation_score > 70
    assert any("BUY_INTEREST" in reason for reason in explained.recommendation_reasons)
    assert any("재무 필터 통과" in reason for reason in explained.recommendation_reasons)
    assert explained.filter_reasons == []


def test_recommendation_explainability_records_exclusion_reasons() -> None:
    service = StrategyService(session=None)
    stock = _stock(
        "000660",
        "GC_ACTIVE",
        screening_score=Decimal("10"),
        ma_gap_ratio=15.0,
        financial_filter_status="FAIL",
    )

    explained = service._attach_recommendation_explainability(
        stock,
        target_state_set={"OPTIMAL_BUY", "BUY_INTEREST"},
        min_recommendation_score=50.0,
    )

    assert explained.recommendation_score is not None
    assert explained.recommendation_score < 50
    assert "대상 상태 제외 (GC_ACTIVE)" in explained.filter_reasons
    assert any("추천 점수 미달" in reason for reason in explained.filter_reasons)
    assert "재무 필터 미통과" in explained.filter_reasons
    assert any("MA 갭 과대" in reason for reason in explained.filter_reasons)


async def test_recommendation_path_applies_financial_filter_and_builds_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.application.domain.strategy.buy_strategy_service import BuyStrategyService

    service = StrategyService(session=None)
    raw_scan = GoldenCrossScanListDTO(
        stocks=[
            _stock("A", "BUY_INTEREST", financial_filter_status=None),
            _stock("B", "READY_TO_BUY", financial_filter_status=None),
            _stock("C", "GC_ACTIVE", financial_filter_status=None),
        ],
        total_scanned=3,
        gc_active_count=3,
        pullback_waiting_count=0,
        buy_interest_count=1,
        ready_to_buy_count=1,
        optimal_buy_count=0,
        scan_time=datetime(2024, 1, 1),
        errors=[],
    )

    async def fake_scan(self, **kwargs):
        _ = self, kwargs
        return raw_scan

    async def fake_financial_filter(self, scan_result, target_states, max_concurrent):
        _ = self, target_states, max_concurrent
        return scan_result.model_copy(
            update={
                "stocks": [
                    scan_result.stocks[0].model_copy(update={"financial_filter_status": "PASS"}),
                    scan_result.stocks[1].model_copy(update={"financial_filter_status": "FAIL"}),
                    scan_result.stocks[2].model_copy(update={"financial_filter_status": "PENDING"}),
                ],
                "financial_pass_count": 1,
                "financial_fail_count": 1,
                "financial_pending_count": 1,
            }
        )

    monkeypatch.setattr(BuyStrategyService, "scan_golden_cross_candidates", fake_scan)
    monkeypatch.setattr(BuyStrategyService, "apply_financial_filter", fake_financial_filter)

    result = await StrategyService.get_golden_cross_recommendations.__wrapped__(
        service,
        object(),
        top_n=5,
        target_states=["OPTIMAL_BUY", "BUY_INTEREST", "READY_TO_BUY"],
        apply_financial_filter=True,
    )

    assert result.buy_candidate_count == 1
    assert result.candidate_state_counts == {"BUY_INTEREST": 1}
    assert result.financial_status_counts == {"PASS": 1}
    assert result.excluded_count == 2
    assert result.top_stocks[0].symbol == "A"
    assert any("재무 필터 통과" in reason for reason in result.top_stocks[0].recommendation_reasons)
    assert any("financial_filter=applied" == item for item in result.selection_criteria)


async def test_recommendation_default_preserves_scan_only_optimal_buy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.application.domain.strategy.buy_strategy_service import BuyStrategyService

    service = StrategyService(session=None)
    raw_scan = GoldenCrossScanListDTO(
        stocks=[
            _stock("A", "OPTIMAL_BUY", financial_filter_status=None),
            _stock("B", "BUY_INTEREST", financial_filter_status=None),
        ],
        total_scanned=2,
        gc_active_count=2,
        pullback_waiting_count=0,
        buy_interest_count=1,
        ready_to_buy_count=0,
        optimal_buy_count=1,
        scan_time=datetime(2024, 1, 1),
        errors=[],
    )

    async def fake_scan(self, **kwargs):
        _ = self, kwargs
        return raw_scan

    async def fail_if_financial_filter_called(self, scan_result, target_states, max_concurrent):
        _ = self, scan_result, target_states, max_concurrent
        raise AssertionError(
            "financial filter should be opt-in for recommendation GET compatibility"
        )

    monkeypatch.setattr(BuyStrategyService, "scan_golden_cross_candidates", fake_scan)
    monkeypatch.setattr(
        BuyStrategyService,
        "apply_financial_filter",
        fail_if_financial_filter_called,
    )

    result = await StrategyService.get_golden_cross_recommendations.__wrapped__(
        service,
        object(),
        top_n=5,
    )

    assert result.buy_candidate_count == 1
    assert result.top_stocks[0].symbol == "A"
    assert result.candidate_state_counts == {"OPTIMAL_BUY": 1}
    assert result.financial_status_counts == {"NOT_CHECKED": 1}
    assert "financial_filter=disabled" in result.selection_criteria


async def test_recommendation_financial_filter_failure_degrades_to_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.application.domain.strategy.buy_strategy_service import BuyStrategyService

    service = StrategyService(session=None)
    raw_scan = GoldenCrossScanListDTO(
        stocks=[_stock("A", "OPTIMAL_BUY", financial_filter_status=None)],
        total_scanned=1,
        gc_active_count=1,
        pullback_waiting_count=0,
        buy_interest_count=0,
        ready_to_buy_count=0,
        optimal_buy_count=1,
        scan_time=datetime(2024, 1, 1),
        errors=[],
    )

    async def fake_scan(self, **kwargs):
        _ = self, kwargs
        return raw_scan

    async def failing_financial_filter(self, scan_result, target_states, max_concurrent):
        _ = self, scan_result, target_states, max_concurrent
        raise RuntimeError("dart unavailable")

    monkeypatch.setattr(BuyStrategyService, "scan_golden_cross_candidates", fake_scan)
    monkeypatch.setattr(BuyStrategyService, "apply_financial_filter", failing_financial_filter)

    result = await StrategyService.get_golden_cross_recommendations.__wrapped__(
        service,
        object(),
        apply_financial_filter=True,
    )

    assert result.buy_candidate_count == 1
    assert result.top_stocks[0].symbol == "A"
    assert result.errors == ["Financial filter skipped: dart unavailable"]
    assert "financial_filter=requested_failed" in result.selection_criteria


async def test_recommendation_all_financial_errors_degrades_to_scan_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.application.domain.strategy.buy_strategy_service import BuyStrategyService

    service = StrategyService(session=None)
    raw_scan = GoldenCrossScanListDTO(
        stocks=[_stock("A", "OPTIMAL_BUY", financial_filter_status=None)],
        total_scanned=1,
        gc_active_count=1,
        pullback_waiting_count=0,
        buy_interest_count=0,
        ready_to_buy_count=0,
        optimal_buy_count=1,
        scan_time=datetime(2024, 1, 1),
        errors=[],
    )

    async def fake_scan(self, **kwargs):
        _ = self, kwargs
        return raw_scan

    async def all_error_financial_filter(self, scan_result, target_states, max_concurrent):
        _ = self, target_states, max_concurrent
        return scan_result.model_copy(
            update={
                "stocks": [
                    scan_result.stocks[0].model_copy(update={"financial_filter_status": "ERROR"})
                ],
                "financial_error_count": 1,
            }
        )

    monkeypatch.setattr(BuyStrategyService, "scan_golden_cross_candidates", fake_scan)
    monkeypatch.setattr(BuyStrategyService, "apply_financial_filter", all_error_financial_filter)

    result = await StrategyService.get_golden_cross_recommendations.__wrapped__(
        service,
        object(),
        apply_financial_filter=True,
    )

    assert result.buy_candidate_count == 1
    assert result.top_stocks[0].symbol == "A"
    assert result.top_stocks[0].financial_filter_status is None
    assert result.errors == ["Financial filter skipped: all target financial screenings failed"]
    assert "financial_filter=requested_failed" in result.selection_criteria


def test_recommendation_target_states_validation_rejects_typos() -> None:
    with pytest.raises(StrategyError):
        StrategyService._validate_recommendation_target_states(["OPTIMAL_BUYY"])
