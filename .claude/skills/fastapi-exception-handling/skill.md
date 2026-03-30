---
name: fastapi-exception-handling
description: FastAPI 예외 처리 아키텍처. 커스텀 예외 클래스, 글로벌 핸들러, 도메인별 예외 분리를 통해 라우트에서 HTTPException 제거하고 클린 코드를 유지합니다.
---

# FastAPI Exception Handling

## 개요

라우트에 분산된 예외 처리를 중앙화하여 클린 코드를 유지하는 아키텍처입니다.
커스텀 예외 클래스와 글로벌 핸들러를 통해 비즈니스 로직과 에러 처리를 분리합니다.

---

## 핵심 원칙

1. **HTTPException 제거** - 라우트/서비스에서 HTTPException 직접 사용 금지
2. **도메인 예외 사용** - 비즈니스 의미를 담은 커스텀 예외 정의
3. **글로벌 핸들러** - 예외 → HTTP 응답 변환을 한 곳에서 관리
4. **계층 구조** - 베이스 예외를 상속하여 일관된 구조 유지
5. **테스트 용이성** - FastAPI 없이도 예외 동작 테스트 가능

---

## 파일 역할 분리 (SSOT)

### 아키텍처 개요

```
┌─────────────────────────────────────────────────────────────────┐
│                         Request Flow                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   Client Request                                                │
│        ↓                                                        │
│   ┌─────────────┐    ┌─────────────────┐    ┌───────────────┐  │
│   │   Router    │ →  │    Service      │ →  │  Repository   │  │
│   │ (Interface) │    │    (Domain)     │    │  (Adapters)   │  │
│   └─────────────┘    └─────────────────┘    └───────────────┘  │
│        ↑                    │                                   │
│        │            raise ApplicationError                      │
│        │                    ↓                                   │
│   ┌─────────────────────────────────────────────────────────┐  │
│   │              exception_handlers.py                       │  │
│   │         (Global Exception → HTTP Response)               │  │
│   └─────────────────────────────────────────────────────────┘  │
│        ↓                                                        │
│   JSON Response                                                 │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 파일별 책임

| 파일 | 위치 | 역할 | 책임 |
|------|------|------|------|
| **exceptions.py** | `common/` 또는 `core/` | 예외 정의 | "무엇을" - 도메인 예외 클래스 정의 (SSOT) |
| **exception_handlers.py** | `settings/` 또는 `core/` | 예외 처리 | "어떻게" - 예외를 HTTP 응답으로 변환 |

---

## exceptions.py - 예외 클래스 정의

### 역할
- **모든 커스텀 예외의 Single Source of Truth (SSOT)**
- 도메인 로직에서 발생하는 예외의 의미와 속성 정의
- HTTP 상태 코드, 에러 코드, 메시지, 상세 정보 캡슐화
- FastAPI/HTTP에 대한 의존성 없음 (순수 Python)

### 권장 위치
```
src/
├── common/exceptions.py      # 공통 레이어에 배치
├── core/exceptions.py        # 또는 코어 레이어에 배치
└── application/common/exceptions.py  # 또는 애플리케이션 공통에 배치
```

### 베이스 클래스

```python
# exceptions.py

from typing import Any


class ApplicationError(Exception):
    """
    애플리케이션 기본 예외

    모든 커스텀 예외의 베이스 클래스.
    HTTP 상태 코드, 에러 코드, 메시지, 상세 정보를 캡슐화합니다.
    """

    def __init__(
        self,
        message: str,
        code: str | None = None,
        status_code: int = 500,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or self.__class__.__name__
        self.status_code = status_code
        self.details = details or {}

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"

    def to_dict(self) -> dict[str, Any]:
        """예외를 딕셔너리로 변환"""
        return {
            "code": self.code,
            "message": self.message,
            "status_code": self.status_code,
            "details": self.details,
        }
```

### 속성 설명

| 속성 | 타입 | 설명 | 예시 |
|------|------|------|------|
| `message` | str | 사람이 읽을 수 있는 에러 메시지 | "User not found: 12345" |
| `code` | str | 머신 파싱용 에러 코드 | "RESOURCE_NOT_FOUND" |
| `status_code` | int | HTTP 상태 코드 | 404 |
| `details` | dict | 추가 디버깅 정보 | {"resource": "User", "id": "12345"} |

### 도메인 예외 정의 예시

```python
# ==================== Validation Exceptions (400) ====================

class ValidationError(ApplicationError):
    """검증 실패 예외"""

    def __init__(self, message: str = "Validation failed", details: dict[str, Any] | None = None):
        super().__init__(message, code="VALIDATION_ERROR", status_code=400, details=details)


class InvalidInputError(ValidationError):
    """잘못된 입력 예외"""

    def __init__(self, field: str, message: str = "Invalid input"):
        super().__init__(
            message=f"Invalid input for field: {field}",
            details={"field": field, "error": message},
        )


# ==================== Resource Exceptions (404, 409) ====================

class NotFoundError(ApplicationError):
    """리소스를 찾을 수 없음 예외"""

    def __init__(self, message: str = "Resource not found"):
        super().__init__(message, code="NOT_FOUND", status_code=404)


class ResourceNotFoundError(ApplicationError):
    """특정 리소스를 찾을 수 없음 예외"""

    def __init__(self, resource: str, identifier: str | int):
        super().__init__(
            message=f"{resource} not found: {identifier}",
            code="RESOURCE_NOT_FOUND",
            status_code=404,
            details={"resource": resource, "identifier": str(identifier)},
        )


class ResourceAlreadyExistsError(ApplicationError):
    """리소스가 이미 존재함 예외"""

    def __init__(self, resource: str, identifier: str | int):
        super().__init__(
            message=f"{resource} already exists: {identifier}",
            code="RESOURCE_ALREADY_EXISTS",
            status_code=409,
            details={"resource": resource, "identifier": str(identifier)},
        )


# ==================== Authorization Exceptions (401, 403) ====================

class AuthenticationError(ApplicationError):
    """인증 실패 예외"""

    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message, code="AUTHENTICATION_ERROR", status_code=401)


class AuthorizationError(ApplicationError):
    """권한 부족 예외"""

    def __init__(self, message: str = "Authorization failed"):
        super().__init__(message, code="AUTHORIZATION_ERROR", status_code=403)


# ==================== Business Logic Exceptions (422) ====================

class BusinessLogicError(ApplicationError):
    """비즈니스 로직 예외"""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(
            message=message,
            code="BUSINESS_LOGIC_ERROR",
            status_code=422,
            details=details
        )


# ==================== External Service Exceptions (502, 503) ====================

class ExternalServiceError(ApplicationError):
    """외부 서비스 오류 예외"""

    def __init__(self, service: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(
            message=f"{service} error: {message}",
            code="EXTERNAL_SERVICE_ERROR",
            status_code=502,
            details=details,
        )


class ServiceUnavailableError(ApplicationError):
    """서비스 사용 불가 예외"""

    def __init__(self, message: str = "Service unavailable"):
        super().__init__(message, code="SERVICE_UNAVAILABLE", status_code=503)
```

---

## exception_handlers.py - 예외 핸들러

### 역할
- **예외를 HTTP 응답으로 변환하는 단일 진입점**
- 모든 예외 타입에 대해 통일된 응답 포맷 보장
- 로깅 및 모니터링 통합 지점
- FastAPI 앱에 핸들러 일괄 등록

### 권장 위치
```
src/
├── settings/exception_handlers.py  # 앱 설정 레이어
├── core/exception_handlers.py      # 또는 코어 레이어
└── config/exception_handlers.py    # 또는 설정 레이어
```

### 핸들러 구조

```python
# exception_handlers.py

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from your_app.exceptions import ApplicationError  # 경로는 프로젝트에 맞게 수정

logger = logging.getLogger(__name__)


async def application_error_handler(request: Request, exc: ApplicationError) -> JSONResponse:
    """
    ApplicationError 핸들러

    모든 도메인 예외를 통일된 JSON 응답 포맷으로 변환합니다.
    """
    logger.warning(
        "ApplicationError: [%s] %s (path=%s)",
        exc.code,
        exc.message,
        request.url.path,
    )

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "message": exc.message,
            "data": None,
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": jsonable_encoder(exc.details),
            },
        },
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """
    HTTPException 핸들러

    FastAPI 기본 HTTPException을 통일된 JSON 응답 포맷으로 변환합니다.
    (의존성, 미들웨어 등에서 발생하는 HTTPException 처리)
    """
    logger.warning(
        "HTTPException: status=%s, detail=%s (path=%s)",
        exc.status_code,
        exc.detail,
        request.url.path,
    )

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "message": str(exc.detail),
            "data": None,
            "error": {
                "code": "HTTP_EXCEPTION",
                "message": str(exc.detail),
                "details": {},
            },
        },
    )


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """
    RequestValidationError 핸들러

    Pydantic 검증 실패를 통일된 JSON 응답 포맷으로 변환합니다.
    """
    errors = exc.errors()
    first_error = errors[0] if errors else {}
    field = ".".join(str(loc) for loc in first_error.get("loc", ["unknown"]))
    msg = first_error.get("msg", "Validation error")

    logger.warning(
        "ValidationError: field=%s, msg=%s (path=%s)",
        field,
        msg,
        request.url.path,
    )

    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "message": f"Validation error: {msg}",
            "data": None,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": f"Invalid input for field: {field}",
                "details": jsonable_encoder({"errors": errors}),
            },
        },
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    범용 예외 핸들러 (Fallback)

    예상치 못한 예외를 처리합니다.
    프로덕션에서는 상세 정보를 숨기고, 개발 환경에서만 노출합니다.
    """
    import os
    debug = os.getenv("DEBUG", "false").lower() == "true"

    logger.exception(
        "Unhandled exception: %s (path=%s)",
        str(exc),
        request.url.path,
    )

    detail = str(exc) if debug else "An unexpected error occurred"

    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "message": "Internal Server Error",
            "data": None,
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": detail,
                "details": {},
            },
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    """
    예외 핸들러 일괄 등록

    등록 순서가 우선순위를 결정합니다.
    더 구체적인 예외 타입을 먼저 등록합니다.

    Args:
        app: FastAPI 앱 인스턴스
    """
    # 1. 커스텀 도메인 예외 (가장 높은 우선순위)
    app.add_exception_handler(ApplicationError, application_error_handler)

    # 2. FastAPI HTTPException (의존성/미들웨어에서 발생)
    app.add_exception_handler(HTTPException, http_exception_handler)

    # 3. Pydantic 검증 에러
    app.add_exception_handler(RequestValidationError, validation_error_handler)

    # 4. 예상치 못한 예외 (Fallback, 가장 낮은 우선순위)
    app.add_exception_handler(Exception, generic_exception_handler)

    logger.info("Exception handlers registered")
```

### 핸들러 등록 (main.py)

```python
# main.py
from fastapi import FastAPI
from your_app.exception_handlers import register_exception_handlers

app = FastAPI(...)

# 예외 핸들러 등록
register_exception_handlers(app)
```

---

## 예외 계층 구조

### 권장 계층도

```
ApplicationError (Base, 500)
│
├── Validation Exceptions (400)
│   ├── ValidationError
│   ├── InvalidInputError
│   └── MissingFieldError
│
├── Resource Exceptions (404, 409)
│   ├── NotFoundError (404)
│   ├── ResourceNotFoundError (404)
│   ├── ResourceAlreadyExistsError (409)
│   └── ResourceConflictError (409)
│
├── Authorization Exceptions (401, 403)
│   ├── AuthenticationError (401)
│   │   ├── TokenExpiredError
│   │   └── InvalidTokenError
│   └── AuthorizationError (403)
│
├── Business Logic Exceptions (422)
│   ├── BusinessLogicError
│   └── [도메인별 예외 확장]
│
├── External Service Exceptions (502, 503)
│   ├── ExternalServiceError (502)
│   └── ServiceUnavailableError (503)
│
├── Rate Limit Exceptions (429)
│   └── RateLimitExceededError
│
├── Timeout Exceptions (504)
│   └── TimeoutError
│
└── Configuration Exceptions (500)
    └── ConfigurationError
```

### HTTP 상태 코드 매핑

| 상태 코드 | 예외 카테고리 | 의미 | 사용 시점 |
|-----------|--------------|------|----------|
| 400 | ValidationError | 클라이언트 입력 오류 | 형식/타입 오류 |
| 401 | AuthenticationError | 인증 실패 | 토큰 없음/만료 |
| 403 | AuthorizationError | 권한 부족 | 접근 거부 |
| 404 | NotFoundError | 리소스 없음 | 존재하지 않는 리소스 |
| 409 | ResourceConflictError | 리소스 충돌 | 중복 생성 |
| 422 | BusinessLogicError | 비즈니스 규칙 위반 | 도메인 로직 실패 |
| 429 | RateLimitExceededError | 요청 제한 초과 | Rate Limit |
| 500 | ConfigurationError | 서버 설정 오류 | 내부 설정 오류 |
| 502 | ExternalServiceError | 외부 서비스 오류 | 외부 API 실패 |
| 503 | ServiceUnavailableError | 서비스 사용 불가 | 서비스 준비 안됨 |
| 504 | TimeoutError | 요청 시간 초과 | 타임아웃 |

---

## 응답 포맷

### 통일된 에러 응답

모든 예외는 동일한 JSON 구조로 반환됩니다:

```json
{
    "success": false,
    "message": "사람이 읽을 수 있는 에러 메시지",
    "data": null,
    "error": {
        "code": "ERROR_CODE",
        "message": "상세 에러 메시지",
        "details": {
            "key": "추가 정보"
        }
    }
}
```

### 필드 설명

| 필드 | 타입 | 설명 |
|------|------|------|
| `success` | bool | 항상 `false` |
| `message` | string | 사용자에게 표시할 메시지 |
| `data` | null | 에러 시 항상 `null` |
| `error.code` | string | 머신 파싱용 에러 코드 |
| `error.message` | string | 상세 에러 메시지 |
| `error.details` | object | 추가 디버깅 정보 |

### 응답 예시

#### ResourceNotFoundError (404)
```json
{
    "success": false,
    "message": "User not found: 12345",
    "data": null,
    "error": {
        "code": "RESOURCE_NOT_FOUND",
        "message": "User not found: 12345",
        "details": {
            "resource": "User",
            "identifier": "12345"
        }
    }
}
```

#### ValidationError (422)
```json
{
    "success": false,
    "message": "Validation error: Field required",
    "data": null,
    "error": {
        "code": "VALIDATION_ERROR",
        "message": "Invalid input for field: body.email",
        "details": {
            "errors": [
                {
                    "type": "missing",
                    "loc": ["body", "email"],
                    "msg": "Field required",
                    "input": {}
                }
            ]
        }
    }
}
```

#### BusinessLogicError (422)
```json
{
    "success": false,
    "message": "Insufficient balance",
    "data": null,
    "error": {
        "code": "BUSINESS_LOGIC_ERROR",
        "message": "Insufficient balance",
        "details": {
            "required": 10000,
            "available": 5000
        }
    }
}
```

---

## 사용 패턴

### 권장 패턴

```python
# ✅ 서비스에서 도메인 예외 발생
class UserService:
    async def get_user(self, user_id: int):
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise ResourceNotFoundError("User", user_id)
        return user

    async def create_user(self, email: str):
        existing = await self.user_repo.get_by_email(email)
        if existing:
            raise ResourceAlreadyExistsError("User", email)
        return await self.user_repo.create(email=email)


# ✅ 라우트는 서비스 호출만 (예외 처리 없음)
@router.get("/users/{user_id}")
async def get_user(
    user_id: int,
    service: UserService = Depends(get_user_service),
):
    # 예외는 글로벌 핸들러가 처리
    user = await service.get_user(user_id)
    return {"success": True, "data": user, "message": "User retrieved"}
```

### 금지 패턴

```python
# ❌ 라우트에서 HTTPException 직접 사용
@router.get("/users/{user_id}")
async def get_user(user_id: int):
    user = await get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")  # 금지!
    return user


# ❌ 서비스에서 HTTPException 사용
class UserService:
    async def get_user(self, user_id: int):
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="...")  # 금지!


# ❌ 라우트에서 try-except로 예외 처리
@router.get("/users/{user_id}")
async def get_user(user_id: int, service: UserService):
    try:
        return await service.get_user(user_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))  # 금지!
```

---

## 새 예외 추가 가이드

### 1. 적절한 부모 클래스 선택

| 상황 | 부모 클래스 | HTTP Status |
|------|------------|-------------|
| 입력 검증 실패 | `ValidationError` | 400 |
| 인증 실패 | `AuthenticationError` | 401 |
| 권한 부족 | `AuthorizationError` | 403 |
| 리소스 없음 | `NotFoundError` | 404 |
| 리소스 충돌 | `ResourceConflictError` | 409 |
| 비즈니스 규칙 위반 | `BusinessLogicError` | 422 |
| 외부 서비스 오류 | `ExternalServiceError` | 502 |
| 서비스 사용 불가 | `ServiceUnavailableError` | 503 |

### 2. 예외 클래스 작성

```python
# exceptions.py

class InsufficientBalanceError(BusinessLogicError):
    """잔고 부족 예외"""

    def __init__(self, required: float, available: float):
        super().__init__(
            message="Insufficient balance",
            details={"required": required, "available": available},
        )


class PaymentFailedError(ExternalServiceError):
    """결제 실패 예외"""

    def __init__(self, provider: str, reason: str):
        super().__init__(
            service=provider,
            message=f"Payment failed: {reason}",
            details={"provider": provider, "reason": reason},
        )
```

### 3. 서비스에서 사용

```python
from your_app.exceptions import InsufficientBalanceError

class PaymentService:
    async def process_payment(self, user_id: int, amount: float):
        balance = await self.get_balance(user_id)
        if balance < amount:
            raise InsufficientBalanceError(required=amount, available=balance)
        # 결제 처리...
```

---

## 테스트

### 예외 핸들러 테스트

```python
# tests/test_exception_handlers.py

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from your_app.exceptions import (
    NotFoundError,
    ResourceNotFoundError,
    BusinessLogicError,
)
from your_app.exception_handlers import register_exception_handlers


def create_test_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/test/not-found")
    async def raise_not_found():
        raise NotFoundError("Test resource not found")

    @app.get("/test/resource-not-found")
    async def raise_resource_not_found():
        raise ResourceNotFoundError("User", 12345)

    @app.get("/test/business-error")
    async def raise_business_error():
        raise BusinessLogicError("Operation not allowed", {"reason": "test"})

    return app


@pytest.fixture
def client():
    app = create_test_app()
    return TestClient(app, raise_server_exceptions=False)


class TestExceptionHandlers:
    def test_not_found_returns_404(self, client):
        response = client.get("/test/not-found")
        assert response.status_code == 404
        data = response.json()
        assert data["success"] is False
        assert data["error"]["code"] == "NOT_FOUND"

    def test_resource_not_found_includes_details(self, client):
        response = client.get("/test/resource-not-found")
        assert response.status_code == 404
        data = response.json()
        assert data["error"]["details"]["resource"] == "User"
        assert data["error"]["details"]["identifier"] == "12345"

    def test_business_error_returns_422(self, client):
        response = client.get("/test/business-error")
        assert response.status_code == 422
        data = response.json()
        assert data["error"]["code"] == "BUSINESS_LOGIC_ERROR"
```

---

## 체크리스트

### 예외 처리 구현

```
□ ApplicationError 베이스 클래스 정의 (exceptions.py)
□ 도메인별 예외 클래스 정의 (exceptions.py)
□ 글로벌 예외 핸들러 작성 (exception_handlers.py)
□ HTTPException 핸들러 추가 (통일된 포맷)
□ main.py에 register_exception_handlers() 호출
□ 서비스에서 커스텀 예외 사용
□ 라우트에서 HTTPException/try-except 제거
□ 예외 핸들러 테스트 작성
```

### 새 예외 추가

```
□ 적절한 부모 클래스 선택
□ status_code, code, message, details 정의
□ exceptions.py 적절한 섹션에 추가
□ 서비스에서 사용
□ 테스트 작성
```

---

## Do / Don't

| DO | DON'T |
|----|-------|
| 서비스에서 커스텀 예외 발생 | 라우트에서 HTTPException 사용 |
| ApplicationError 상속 | 빌트인 Exception 직접 사용 |
| 의미 있는 error code 정의 | 하드코딩된 에러 메시지 |
| details에 디버깅 정보 포함 | 민감 정보 노출 (비밀번호, 토큰 등) |
| 글로벌 핸들러에서 일괄 처리 | 각 라우트에서 try-except |
| jsonable_encoder로 직렬화 | details에 non-JSON 타입 포함 |
| 예외 단위 테스트 작성 | FastAPI 의존 테스트만 작성 |

---

## 디렉토리 구조 예시

### 일반적인 FastAPI 프로젝트

```
src/
├── main.py                    # FastAPI 앱 + 핸들러 등록
├── settings/
│   ├── config.py              # 환경 설정
│   └── exception_handlers.py  # 예외 핸들러
├── common/
│   ├── exceptions.py          # 예외 클래스 정의 (SSOT)
│   └── dto.py                 # 공통 DTO
├── domain/
│   ├── user/
│   │   ├── service.py         # 예외 발생 위치
│   │   └── router.py          # 예외 처리 없음
│   └── product/
│       ├── service.py
│       └── router.py
└── tests/
    └── test_exception_handlers.py
```

### 헥사고날 아키텍처

```
src/
├── main.py
├── settings/
│   └── exception_handlers.py
├── application/
│   ├── common/
│   │   └── exceptions.py      # 예외 클래스 정의
│   ├── interface/
│   │   └── api/               # 라우터 (예외 처리 없음)
│   └── domain/
│       └── {feature}/
│           └── service.py     # 예외 발생 위치
└── adapters/
    └── ...
```

---

## 참고

- [FastAPI Handling Errors](https://fastapi.tiangolo.com/tutorial/handling-errors/)
- [FastAPI Custom Exception Handlers](https://fastapi.tiangolo.com/tutorial/handling-errors/#install-custom-exception-handlers)
- [Pydantic Validation Errors](https://docs.pydantic.dev/latest/concepts/validation/)
