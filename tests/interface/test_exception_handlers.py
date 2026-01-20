# -*- coding: utf-8 -*-
"""
Exception Handlers Tests - 예외 핸들러 통합 테스트

예외 처리 중앙화가 올바르게 동작하는지 검증합니다.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from src.application.common.exceptions import (
    ApplicationError,
    AuthorizationError,
    BacktestError,
    BusinessLogicError,
    ExternalServiceError,
    NotFoundError,
    ResourceNotFoundError,
    ServiceUnavailableError,
    ValidationError,
)
from src.settings.exception_handlers import register_exception_handlers


# ==================== Test App Setup ====================


def create_test_app() -> FastAPI:
    """테스트용 FastAPI 앱 생성"""
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/test/not-found")
    async def raise_not_found():
        raise NotFoundError("Test resource not found")

    @app.get("/test/resource-not-found")
    async def raise_resource_not_found():
        raise ResourceNotFoundError("Strategy", 12345)

    @app.get("/test/validation-error")
    async def raise_validation_error():
        raise ValidationError("Invalid input", details={"field": "symbol"})

    @app.get("/test/authorization-error")
    async def raise_authorization_error():
        raise AuthorizationError("Access denied from IP: 192.168.1.1")

    @app.get("/test/business-logic-error")
    async def raise_business_logic_error():
        raise BusinessLogicError("Order quantity exceeds limit", details={"max": 100})

    @app.get("/test/external-service-error")
    async def raise_external_service_error():
        raise ExternalServiceError("KIS API", "credentials not configured")

    @app.get("/test/backtest-error")
    async def raise_backtest_error():
        raise BacktestError("Insufficient data", details={"required": 60, "actual": 30})

    @app.get("/test/generic-exception")
    async def raise_generic_exception():
        raise RuntimeError("Unexpected error occurred")

    @app.get("/test/service-unavailable")
    async def raise_service_unavailable():
        raise ServiceUnavailableError("KIS API credentials not configured")

    @app.get("/test/http-exception")
    async def raise_http_exception():
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Unauthorized access")

    @app.post("/test/pydantic-validation")
    async def pydantic_validation(data: dict):
        # Pydantic이 자동으로 ValidationError를 발생시킴
        pass

    return app


@pytest.fixture
def client():
    """동기 테스트 클라이언트"""
    app = create_test_app()
    # raise_server_exceptions=False: 서버 예외를 HTTP 응답으로 변환
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
async def async_client():
    """비동기 테스트 클라이언트"""
    app = create_test_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


# ==================== Response Format Tests ====================


class TestResponseFormat:
    """응답 포맷 검증 테스트"""

    def test_error_response_has_required_fields(self, client):
        """에러 응답에 필수 필드가 포함되어야 함"""
        response = client.get("/test/not-found")
        data = response.json()

        # 필수 필드 존재 확인
        assert "success" in data
        assert "message" in data
        assert "data" in data
        assert "error" in data

        # 에러 객체 필드 확인
        assert "code" in data["error"]
        assert "message" in data["error"]
        assert "details" in data["error"]

    def test_error_response_success_is_false(self, client):
        """에러 응답의 success는 항상 false"""
        response = client.get("/test/not-found")
        data = response.json()

        assert data["success"] is False

    def test_error_response_data_is_null(self, client):
        """에러 응답의 data는 항상 null"""
        response = client.get("/test/not-found")
        data = response.json()

        assert data["data"] is None


# ==================== Status Code Tests ====================


class TestStatusCodes:
    """HTTP 상태 코드 검증 테스트"""

    def test_not_found_returns_404(self, client):
        """NotFoundError는 404 반환"""
        response = client.get("/test/not-found")
        assert response.status_code == 404

    def test_resource_not_found_returns_404(self, client):
        """ResourceNotFoundError는 404 반환"""
        response = client.get("/test/resource-not-found")
        assert response.status_code == 404

    def test_validation_error_returns_400(self, client):
        """ValidationError는 400 반환"""
        response = client.get("/test/validation-error")
        assert response.status_code == 400

    def test_authorization_error_returns_403(self, client):
        """AuthorizationError는 403 반환"""
        response = client.get("/test/authorization-error")
        assert response.status_code == 403

    def test_business_logic_error_returns_422(self, client):
        """BusinessLogicError는 422 반환"""
        response = client.get("/test/business-logic-error")
        assert response.status_code == 422

    def test_external_service_error_returns_502(self, client):
        """ExternalServiceError는 502 반환"""
        response = client.get("/test/external-service-error")
        assert response.status_code == 502

    def test_generic_exception_returns_500(self, client):
        """일반 예외는 500 반환"""
        response = client.get("/test/generic-exception")
        assert response.status_code == 500

    def test_service_unavailable_returns_503(self, client):
        """ServiceUnavailableError는 503 반환"""
        response = client.get("/test/service-unavailable")
        assert response.status_code == 503

    def test_http_exception_returns_correct_status(self, client):
        """HTTPException은 해당 상태 코드 반환"""
        response = client.get("/test/http-exception")
        assert response.status_code == 401


# ==================== Error Code Tests ====================


class TestErrorCodes:
    """에러 코드 검증 테스트"""

    def test_not_found_error_code(self, client):
        """NotFoundError의 에러 코드"""
        response = client.get("/test/not-found")
        data = response.json()
        assert data["error"]["code"] == "NOT_FOUND"

    def test_resource_not_found_error_code(self, client):
        """ResourceNotFoundError의 에러 코드"""
        response = client.get("/test/resource-not-found")
        data = response.json()
        assert data["error"]["code"] == "RESOURCE_NOT_FOUND"

    def test_validation_error_code(self, client):
        """ValidationError의 에러 코드"""
        response = client.get("/test/validation-error")
        data = response.json()
        assert data["error"]["code"] == "VALIDATION_ERROR"

    def test_authorization_error_code(self, client):
        """AuthorizationError의 에러 코드"""
        response = client.get("/test/authorization-error")
        data = response.json()
        assert data["error"]["code"] == "AUTHORIZATION_ERROR"

    def test_business_logic_error_code(self, client):
        """BusinessLogicError의 에러 코드"""
        response = client.get("/test/business-logic-error")
        data = response.json()
        assert data["error"]["code"] == "BUSINESS_LOGIC_ERROR"

    def test_external_service_error_code(self, client):
        """ExternalServiceError의 에러 코드"""
        response = client.get("/test/external-service-error")
        data = response.json()
        assert data["error"]["code"] == "EXTERNAL_SERVICE_ERROR"

    def test_generic_exception_error_code(self, client):
        """일반 예외의 에러 코드"""
        response = client.get("/test/generic-exception")
        data = response.json()
        assert data["error"]["code"] == "INTERNAL_SERVER_ERROR"

    def test_service_unavailable_error_code(self, client):
        """ServiceUnavailableError의 에러 코드"""
        response = client.get("/test/service-unavailable")
        data = response.json()
        assert data["error"]["code"] == "SERVICE_UNAVAILABLE"

    def test_http_exception_error_code(self, client):
        """HTTPException의 에러 코드"""
        response = client.get("/test/http-exception")
        data = response.json()
        assert data["error"]["code"] == "HTTP_EXCEPTION"


# ==================== Error Details Tests ====================


class TestErrorDetails:
    """에러 상세 정보 검증 테스트"""

    def test_resource_not_found_includes_resource_info(self, client):
        """ResourceNotFoundError에 리소스 정보 포함"""
        response = client.get("/test/resource-not-found")
        data = response.json()

        assert data["error"]["details"]["resource"] == "Strategy"
        assert data["error"]["details"]["identifier"] == "12345"

    def test_validation_error_includes_field_info(self, client):
        """ValidationError에 필드 정보 포함"""
        response = client.get("/test/validation-error")
        data = response.json()

        assert data["error"]["details"]["field"] == "symbol"

    def test_business_logic_error_includes_details(self, client):
        """BusinessLogicError에 상세 정보 포함"""
        response = client.get("/test/business-logic-error")
        data = response.json()

        assert data["error"]["details"]["max"] == 100

    def test_backtest_error_includes_details(self, client):
        """BacktestError에 상세 정보 포함"""
        response = client.get("/test/backtest-error")
        data = response.json()

        assert data["error"]["details"]["required"] == 60
        assert data["error"]["details"]["actual"] == 30


# ==================== Error Message Tests ====================


class TestErrorMessages:
    """에러 메시지 검증 테스트"""

    def test_not_found_message(self, client):
        """NotFoundError 메시지"""
        response = client.get("/test/not-found")
        data = response.json()

        assert "not found" in data["message"].lower()

    def test_external_service_error_message(self, client):
        """ExternalServiceError 메시지에 서비스명 포함"""
        response = client.get("/test/external-service-error")
        data = response.json()

        assert "KIS API" in data["message"]
        assert "credentials" in data["message"]

    def test_authorization_error_message(self, client):
        """AuthorizationError 메시지에 IP 포함"""
        response = client.get("/test/authorization-error")
        data = response.json()

        assert "192.168.1.1" in data["message"]


# ==================== Pydantic Validation Tests ====================


class TestHTTPExceptionHandling:
    """HTTPException 통합 테스트"""

    def test_http_exception_follows_unified_format(self, client):
        """HTTPException도 통일된 포맷으로 반환"""
        response = client.get("/test/http-exception")
        data = response.json()

        # 통일된 포맷 확인
        assert data["success"] is False
        assert data["data"] is None
        assert "error" in data
        assert data["error"]["code"] == "HTTP_EXCEPTION"
        assert "Unauthorized" in data["message"]


class TestPydanticValidation:
    """Pydantic 검증 에러 테스트"""

    def test_pydantic_validation_error_format(self, client):
        """Pydantic ValidationError도 통일된 포맷으로 반환"""
        # dict 타입이 아닌 잘못된 데이터 전송
        response = client.post(
            "/test/pydantic-validation",
            content="invalid json",
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 422
        data = response.json()

        # 통일된 포맷 확인
        assert data["success"] is False
        assert data["data"] is None
        assert "error" in data
        assert data["error"]["code"] == "VALIDATION_ERROR"


# ==================== Async Tests ====================


class TestAsyncExceptionHandling:
    """비동기 예외 처리 테스트"""

    @pytest.mark.asyncio
    async def test_async_not_found(self, async_client):
        """비동기 클라이언트에서 NotFoundError 처리"""
        response = await async_client.get("/test/not-found")

        assert response.status_code == 404
        data = response.json()
        assert data["success"] is False
        assert data["error"]["code"] == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_async_authorization_error(self, async_client):
        """비동기 클라이언트에서 AuthorizationError 처리"""
        response = await async_client.get("/test/authorization-error")

        assert response.status_code == 403
        data = response.json()
        assert data["success"] is False
        assert data["error"]["code"] == "AUTHORIZATION_ERROR"
