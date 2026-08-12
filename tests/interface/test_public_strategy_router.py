# -*- coding: utf-8 -*-
"""공개 전략 API 계약 테스트

- market 외의 파라미터는 조작 불가 (extra body는 서비스에 전달되지 않음)
- 위조된 forwarded header가 신뢰되지 않은 직접 접속에서 무시됨
- 429/503이 표준 응답 포맷으로 매핑됨
- 관리자 의존성 없이 접근 가능
"""

from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.common.dependencies import get_public_strategy_service
from src.application.common.exceptions import (
    RateLimitExceededError,
    ServiceUnavailableError,
)
from src.application.domain.strategy.public_dto import (
    PublicGoldenCrossScanDTO,
    PublicRecommendationSnapshotDTO,
    PublicScanStockDTO,
)
from src.application.interface.api.public_strategy_router import router as public_strategy_router
from src.settings.exception_handlers import register_exception_handlers


def _scan_result() -> PublicGoldenCrossScanDTO:
    return PublicGoldenCrossScanDTO(
        stocks=[
            PublicScanStockDTO(
                symbol="005930",
                name="삼성전자",
                market="KOSPI",
                current_price=70000,
                ma_gap_ratio=2.5,
                stoch_k=25.0,
                stoch_d=30.0,
                gc_state="OPTIMAL_BUY",
            )
        ],
        total_scanned=100,
        gc_active_count=10,
        scan_time=datetime(2026, 8, 13, 11, 30),
        error_count=0,
    )


class StubPublicService:
    def __init__(self, error: Exception | None = None):
        self.scan_calls: list[dict] = []
        self._error = error

    async def run_public_scan(self, market, client_ip):
        self.scan_calls.append({"market": market, "client_ip": client_ip})
        if self._error:
            raise self._error
        return _scan_result()

    async def get_public_recommendations(self):
        return PublicRecommendationSnapshotDTO.empty()


def _build_app(service: StubPublicService) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(public_strategy_router)
    app.dependency_overrides[get_public_strategy_service] = lambda: service
    return app


def test_public_scan_returns_public_payload() -> None:
    service = StubPublicService()
    client = TestClient(_build_app(service), raise_server_exceptions=False)

    response = client.post("/api/v1/public/strategies/golden-cross-scan", json={"market": "KOSPI"})

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["total_scanned"] == 100
    assert body["data"]["stocks"][0]["symbol"] == "005930"
    assert service.scan_calls[0]["market"] == "KOSPI"


def test_public_scan_rejects_invalid_market() -> None:
    service = StubPublicService()
    client = TestClient(_build_app(service), raise_server_exceptions=False)

    response = client.post("/api/v1/public/strategies/golden-cross-scan", json={"market": "NASDAQ"})

    assert response.status_code == 422
    assert service.scan_calls == []


def test_public_scan_ignores_tampering_body_fields() -> None:
    """limit/동시성/재무 필터 등은 요청으로 조작 불가 — market만 서비스에 전달된다."""
    service = StubPublicService()
    client = TestClient(_build_app(service), raise_server_exceptions=False)

    response = client.post(
        "/api/v1/public/strategies/golden-cross-scan",
        json={
            "market": None,
            "limit": 5000,
            "max_concurrent": 50,
            "stoch_threshold": 50,
            "apply_financial_filter": True,
        },
    )

    assert response.status_code == 200
    assert service.scan_calls == [{"market": None, "client_ip": "testclient"}]


def test_forged_forwarded_headers_do_not_change_client_ip() -> None:
    """신뢰되지 않은 직접 접속의 X-Forwarded-For/X-Real-IP는 무시된다 (쿨다운 우회 불가)."""
    service = StubPublicService()
    client = TestClient(_build_app(service), raise_server_exceptions=False)

    client.post(
        "/api/v1/public/strategies/golden-cross-scan",
        json={"market": None},
        headers={"X-Forwarded-For": "1.1.1.1"},
    )
    client.post(
        "/api/v1/public/strategies/golden-cross-scan",
        json={"market": None},
        headers={"X-Forwarded-For": "2.2.2.2", "X-Real-IP": "3.3.3.3"},
    )

    assert [call["client_ip"] for call in service.scan_calls] == ["testclient", "testclient"]


def test_rate_limit_maps_to_429_with_retry_after() -> None:
    service = StubPublicService(error=RateLimitExceededError(retry_after=42))
    client = TestClient(_build_app(service), raise_server_exceptions=False)

    response = client.post("/api/v1/public/strategies/golden-cross-scan", json={"market": None})

    assert response.status_code == 429
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    assert body["error"]["details"]["retry_after"] == 42


def test_service_unavailable_maps_to_503() -> None:
    service = StubPublicService(error=ServiceUnavailableError("Public scan unavailable"))
    client = TestClient(_build_app(service), raise_server_exceptions=False)

    response = client.post("/api/v1/public/strategies/golden-cross-scan", json={"market": None})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"


def test_public_recommendations_return_200_with_available_false() -> None:
    service = StubPublicService()
    client = TestClient(_build_app(service), raise_server_exceptions=False)

    response = client.get("/api/v1/public/strategies/recommendations")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["available"] is False
