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
from src.application.domain.recommendation.dto import RecommendationCandidateListDTO


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
    )

    assert captured_kwargs == {
        "market": "KOSDAQ",
        "stoch_threshold": 25.0,
        "gc_only": False,
        "include_etf": False,
        "limit": 7,
        "max_concurrent": 3,
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
