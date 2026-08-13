# -*- coding: utf-8 -*-
"""공개 전략 API 계약 테스트

- market 외의 파라미터는 조작 불가 (extra body는 서비스에 전달되지 않음)
- 위조된 forwarded header가 신뢰되지 않은 직접 접속에서 무시됨
- 429/503/409가 표준 응답 포맷으로 매핑됨
- 관리자 의존성 없이 접근 가능
- GET /scan-capabilities는 인증 없이 조회되며 ETF 전용 모드에서는 KOSPI/KOSDAQ이 없음
- wire상 유효하지만 비가용한 시장 요청은 409 RESOURCE_CONFLICT(reason=MARKET_NOT_AVAILABLE)
- 정의되지 않은 시장(NASDAQ)은 여전히 Pydantic 422이며 서비스가 호출되지 않음
- market=null은 계속 허용되며, 스캔 성공 응답에는 market/outcome이 포함됨
"""

from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.common.dependencies import get_public_strategy_service
from src.application.common.exceptions import (
    RateLimitExceededError,
    ResourceConflictError,
    ServiceUnavailableError,
)
from src.application.domain.strategy.public_dto import (
    PublicGoldenCrossScanDTO,
    PublicRecommendationSnapshotDTO,
    PublicScanCapabilitiesDTO,
    PublicScanMarketOptionDTO,
    PublicScanStockDTO,
)
from src.application.interface.api.public_strategy_router import router as public_strategy_router
from src.settings.exception_handlers import register_exception_handlers


def _scan_result(market: str | None = "KOSPI") -> PublicGoldenCrossScanDTO:
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
        market=market,
        outcome="MATCHES_FOUND",
    )


def _etf_only_capabilities() -> PublicScanCapabilitiesDTO:
    """운영 기준선: ETF_UNIVERSE_ENABLED=true, ETF 221개 활성 / KOSPI·KOSDAQ 0개."""
    return PublicScanCapabilitiesDTO(
        scan_enabled=True,
        universe_mode="ETF_ONLY",
        allow_all=False,
        default_market="ETF",
        markets=[PublicScanMarketOptionDTO(value="ETF", label="ETF", active_count=221)],
        notice="현재 ETF 전용 유니버스로 운영 중입니다.",
    )


class StubPublicService:
    def __init__(
        self,
        error: Exception | None = None,
        capabilities: PublicScanCapabilitiesDTO | None = None,
        market_errors: dict[str | None, Exception] | None = None,
    ):
        self.scan_calls: list[dict] = []
        self.capability_calls = 0
        self._error = error
        self._capabilities = capabilities if capabilities is not None else _etf_only_capabilities()
        self._market_errors = market_errors or {}

    async def run_public_scan(self, market, client_ip):
        self.scan_calls.append({"market": market, "client_ip": client_ip})
        if market in self._market_errors:
            raise self._market_errors[market]
        if self._error:
            raise self._error
        return _scan_result(market=market)

    async def get_scan_capabilities(self):
        self.capability_calls += 1
        return self._capabilities

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
    # 플랜 4.3 / 6.3: 성공 응답에는 적용된 시장과 결과 상태가 포함되어야 한다.
    assert body["data"]["market"] == "KOSPI"
    assert body["data"]["outcome"] == "MATCHES_FOUND"
    assert service.scan_calls[0]["market"] == "KOSPI"


def test_public_scan_rejects_invalid_market() -> None:
    """정의되지 않은 시장(NASDAQ)은 Pydantic 단계에서 422이며 서비스가 호출되지 않는다."""
    service = StubPublicService()
    client = TestClient(_build_app(service), raise_server_exceptions=False)

    response = client.post("/api/v1/public/strategies/golden-cross-scan", json={"market": "NASDAQ"})

    assert response.status_code == 422
    assert service.scan_calls == []


def test_public_scan_ignores_tampering_body_fields() -> None:
    """limit/동시성/재무 필터 등은 요청으로 조작 불가 — market만 서비스에 전달된다.

    market=None(전체) 요청 형식이 계속 허용됨도 함께 검증한다.
    """
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


def test_public_scan_rejects_unavailable_market_with_standard_409_envelope() -> None:
    """wire상 유효한 KOSPI지만 ETF 전용 운영에서는 비가용 → 409 RESOURCE_CONFLICT."""
    service = StubPublicService(
        market_errors={
            "KOSPI": ResourceConflictError(
                message="Requested market is not available for public scan",
                details={
                    "reason": "MARKET_NOT_AVAILABLE",
                    "requested_market": "KOSPI",
                    "available_markets": ["ETF"],
                    "universe_mode": "ETF_ONLY",
                },
            )
        }
    )
    client = TestClient(_build_app(service), raise_server_exceptions=False)

    response = client.post("/api/v1/public/strategies/golden-cross-scan", json={"market": "KOSPI"})

    assert response.status_code == 409
    body = response.json()
    assert body["success"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "RESOURCE_CONFLICT"
    assert body["error"]["details"]["reason"] == "MARKET_NOT_AVAILABLE"
    assert body["error"]["details"]["requested_market"] == "KOSPI"
    assert body["error"]["details"]["available_markets"] == ["ETF"]
    assert body["error"]["details"]["universe_mode"] == "ETF_ONLY"
    # wire 검증(Literal)은 통과했고, 비가용 판정은 서비스 정책이 내렸음을 보장한다.
    assert service.scan_calls[0]["market"] == "KOSPI"


def test_public_recommendations_return_200_with_available_false() -> None:
    service = StubPublicService()
    client = TestClient(_build_app(service), raise_server_exceptions=False)

    response = client.get("/api/v1/public/strategies/recommendations")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["available"] is False


# ==================== GET /scan-capabilities ====================


def test_scan_capabilities_endpoint_accessible_without_auth() -> None:
    """관리자 의존성 없이 조회 가능하며 서비스가 반환한 값을 그대로 노출한다."""
    service = StubPublicService(capabilities=_etf_only_capabilities())
    client = TestClient(_build_app(service), raise_server_exceptions=False)

    response = client.get("/api/v1/public/strategies/scan-capabilities")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["scan_enabled"] is True
    assert body["data"]["universe_mode"] == "ETF_ONLY"
    assert body["data"]["allow_all"] is False
    assert body["data"]["default_market"] == "ETF"
    assert service.capability_calls == 1


def test_scan_capabilities_etf_mode_excludes_kospi_kosdaq() -> None:
    """ETF 전용 운영 capability 응답에는 KOSPI/KOSDAQ 옵션이 없다."""
    service = StubPublicService(capabilities=_etf_only_capabilities())
    client = TestClient(_build_app(service), raise_server_exceptions=False)

    response = client.get("/api/v1/public/strategies/scan-capabilities")

    markets = response.json()["data"]["markets"]
    values = [m["value"] for m in markets]
    assert values == ["ETF"]
    assert "KOSPI" not in values
    assert "KOSDAQ" not in values


def test_scan_capabilities_no_scan_enabled_returns_200_with_empty_markets() -> None:
    """가용 시장이 전혀 없어도 capability 조회 자체는 200이며 markets=[]다 (플랜 4.1)."""
    empty_capabilities = PublicScanCapabilitiesDTO(
        scan_enabled=False,
        universe_mode="ETF_ONLY",
        allow_all=False,
        default_market=None,
        markets=[],
        notice="현재 스캔 가능한 유니버스를 준비 중입니다.",
    )
    service = StubPublicService(capabilities=empty_capabilities)
    client = TestClient(_build_app(service), raise_server_exceptions=False)

    response = client.get("/api/v1/public/strategies/scan-capabilities")

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["scan_enabled"] is False
    assert body["data"]["markets"] == []
