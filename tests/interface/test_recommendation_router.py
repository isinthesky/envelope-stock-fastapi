# -*- coding: utf-8 -*-
"""
Recommendation Router 테스트

엔드포인트 함수 직접 호출(DI/응답 래핑 검증) + TestClient를 통한 실제 라우팅
검증(admin 게이트가 FastAPI Depends()로 실제 연결되어 있는지 확인)을 함께 둔다.

주의: `admin_access: AdminAccessDep`는 Depends() 기반이라 함수를 직접 호출하는
테스트로는 게이트가 실제로 동작하는지 검증할 수 없다(기본값 None이 그대로 쓰임).
따라서 게이트 자체는 TestClient로 실제 요청을 보내 검증한다.
"""

from datetime import datetime

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import src.application.interface.api.recommendation_router as recommendation_router
from src.application.common.dependencies import get_session, verify_admin_access
from src.application.domain.backtest.validation import WindowMetrics
from src.application.domain.recommendation.dto import (
    RecommendationCandidateListDTO,
    RecommendationRuleCandidateDTO,
    RecommendationRuleSetDTO,
    RecommendationRuleSetListDTO,
    RecommendationRuleSetValidationResultDTO,
    RuleSetStatus,
)
from src.application.interface.api.backtest_router import get_backtest_service


class _StubRecommendationScanService:
    def __init__(self, naver_client, session, candidates=None, captured_kwargs=None) -> None:
        _ = naver_client, session
        self._candidates = candidates or []
        self._captured_kwargs = captured_kwargs

    async def scan_candidates(self, **kwargs):
        if self._captured_kwargs is not None:
            self._captured_kwargs.update(kwargs)
        return RecommendationCandidateListDTO(
            candidates=self._candidates,
            total_scanned=len(self._candidates),
            candidate_count=len(self._candidates),
            generated_at=datetime(2026, 7, 1, 9, 0, 0),
        )


@pytest.mark.asyncio
async def test_get_recommendation_candidates_returns_success_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(recommendation_router, "get_naver_stock_client", lambda: object())
    monkeypatch.setattr(
        recommendation_router, "RecommendationScanService", _StubRecommendationScanService
    )

    response = await recommendation_router.get_recommendation_candidates(session=object())

    assert response.success is True
    assert response.data is not None
    assert response.data.candidate_count == 0


@pytest.mark.asyncio
async def test_get_recommendation_candidates_empty_universe_is_not_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(recommendation_router, "get_naver_stock_client", lambda: object())
    monkeypatch.setattr(
        recommendation_router, "RecommendationScanService", _StubRecommendationScanService
    )

    response = await recommendation_router.get_recommendation_candidates(
        session=object(), market="KOSDAQ", limit=1
    )

    assert response.success is True
    assert response.data.candidates == []


@pytest.mark.asyncio
async def test_get_recommendation_candidates_forwards_query_params_to_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_kwargs: dict = {}
    monkeypatch.setattr(recommendation_router, "get_naver_stock_client", lambda: object())
    monkeypatch.setattr(
        recommendation_router,
        "RecommendationScanService",
        lambda naver_client, session: _StubRecommendationScanService(
            naver_client, session, captured_kwargs=captured_kwargs
        ),
    )

    await recommendation_router.get_recommendation_candidates(
        session=object(),
        market="KOSDAQ",
        stoch_threshold=25.0,
        gc_only=False,
        include_etf=False,
        limit=7,
        max_concurrent=3,
        rule_set_id="1",
    )

    assert captured_kwargs == {
        "market": "KOSDAQ",
        "stoch_threshold": 25.0,
        "gc_only": False,
        "include_etf": False,
        "limit": 7,
        "max_concurrent": 3,
        "rule_set_id": "1",
    }


async def _fake_get_session():
    yield object()


async def _allow_admin_access(request: Request) -> str:
    return "127.0.0.1"


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(recommendation_router.router)
    app.dependency_overrides[get_session] = _fake_get_session
    return app


def test_candidates_route_denies_unauthenticated_client() -> None:
    app = _build_app()
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/api/v1/recommendations/candidates")

    assert response.status_code >= 400


def test_candidates_route_allows_admin_and_returns_wrapped_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(recommendation_router, "get_naver_stock_client", lambda: object())
    monkeypatch.setattr(
        recommendation_router, "RecommendationScanService", _StubRecommendationScanService
    )

    app = _build_app()
    app.dependency_overrides[verify_admin_access] = _allow_admin_access
    try:
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/v1/recommendations/candidates")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["candidate_count"] == 0


_SAMPLE_RULE_SET = RecommendationRuleSetDTO(
    rule_id="1",
    name="golden-cross-swing",
    version=1,
    status=RuleSetStatus.DRAFT,
    candidates=[
        RecommendationRuleCandidateDTO(
            candidate_id="c1", name="baseline", rules={"stoch_oversold": 30.0}
        )
    ],
)

_SAMPLE_WINDOW_METRICS = WindowMetrics(
    cagr=12.0, benchmark_cagr=5.0, mdd=-8.0, sharpe=1.1, turnover=3.0
)


class _StubRuleSetService:
    def __init__(
        self, rule_set=None, list_result=None, validation_result=None, captured=None
    ) -> None:
        self._rule_set = rule_set
        self._list_result = list_result
        self._validation_result = validation_result
        self._captured = captured

    async def create_rule_set(self, request):
        if self._captured is not None:
            self._captured["create_request"] = request
        return self._rule_set

    async def list_rule_sets(self, limit=100, offset=0):
        return self._list_result

    async def validate_rule_set(self, rule_id, request, backtest_service):
        if self._captured is not None:
            self._captured["validate_rule_id"] = rule_id
            self._captured["validate_request"] = request
        return self._validation_result


def test_rule_sets_post_denies_unauthenticated_client() -> None:
    app = _build_app()
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/api/v1/recommendations/rule-sets",
        json={
            "name": "rs",
            "candidates": [{"candidate_id": "c1", "name": "c1", "rules": {"stoch_oversold": 30.0}}],
        },
        headers={"x-requested-with": "XMLHttpRequest"},
    )

    assert response.status_code >= 400


def test_rule_sets_post_allows_admin_and_returns_created_rule_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}
    monkeypatch.setattr(
        recommendation_router,
        "RecommendationRuleSetService",
        lambda: _StubRuleSetService(rule_set=_SAMPLE_RULE_SET, captured=captured),
    )

    app = _build_app()
    app.dependency_overrides[verify_admin_access] = _allow_admin_access
    try:
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post(
            "/api/v1/recommendations/rule-sets",
            json={
                "name": "golden-cross-swing",
                "candidates": [
                    {"candidate_id": "c1", "name": "baseline", "rules": {"stoch_oversold": 30.0}}
                ],
            },
            headers={"x-requested-with": "XMLHttpRequest"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    body = response.json()
    assert body["success"] is True
    assert body["data"]["rule_id"] == "1"
    assert body["data"]["status"] == "draft"
    assert captured["create_request"].name == "golden-cross-swing"


def test_rule_sets_get_denies_unauthenticated_client() -> None:
    app = _build_app()
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/api/v1/recommendations/rule-sets")

    assert response.status_code >= 400


def test_rule_sets_get_allows_admin_and_returns_list(monkeypatch: pytest.MonkeyPatch) -> None:
    list_result = RecommendationRuleSetListDTO(rule_sets=[_SAMPLE_RULE_SET], total_count=1)
    monkeypatch.setattr(
        recommendation_router,
        "RecommendationRuleSetService",
        lambda: _StubRuleSetService(list_result=list_result),
    )

    app = _build_app()
    app.dependency_overrides[verify_admin_access] = _allow_admin_access
    try:
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/v1/recommendations/rule-sets")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["total_count"] == 1
    assert body["data"]["rule_sets"][0]["rule_id"] == "1"


def test_validate_route_denies_unauthenticated_client() -> None:
    app = _build_app()
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/api/v1/recommendations/rule-sets/1/validate",
        json={
            "train_start": "2024-01-01",
            "train_end": "2024-06-30",
            "test_start": "2024-07-01",
            "test_end": "2024-12-31",
            "benchmark": "0001",
        },
        headers={"x-requested-with": "XMLHttpRequest"},
    )

    assert response.status_code >= 400


def test_validate_route_allows_admin_and_returns_result(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}
    validation_result = RecommendationRuleSetValidationResultDTO(
        rule_id="1",
        selected_candidate_id="c1",
        selected_candidate_hash="abc123",
        data_snooping_warning=False,
        train_metrics=_SAMPLE_WINDOW_METRICS,
        test_metrics=_SAMPLE_WINDOW_METRICS,
        report_markdown="# report",
    )
    monkeypatch.setattr(
        recommendation_router,
        "RecommendationRuleSetService",
        lambda: _StubRuleSetService(validation_result=validation_result, captured=captured),
    )

    app = _build_app()
    app.dependency_overrides[verify_admin_access] = _allow_admin_access
    app.dependency_overrides[get_backtest_service] = lambda: object()
    try:
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post(
            "/api/v1/recommendations/rule-sets/1/validate",
            json={
                "train_start": "2024-01-01",
                "train_end": "2024-06-30",
                "test_start": "2024-07-01",
                "test_end": "2024-12-31",
                "benchmark": "0001",
            },
            headers={"x-requested-with": "XMLHttpRequest"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["selected_candidate_id"] == "c1"
    assert body["data"]["selected_candidate_hash"] == "abc123"
    assert captured["validate_rule_id"] == "1"
