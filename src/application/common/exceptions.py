# -*- coding: utf-8 -*-
"""
Common Exceptions - 공통 예외 클래스

애플리케이션 전역에서 사용하는 커스텀 예외 정의
"""

from typing import Any


# ==================== Base Exception ====================


class ApplicationError(Exception):
    """
    애플리케이션 기본 예외

    모든 커스텀 예외의 베이스 클래스
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


# ==================== Validation Exceptions ====================


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


class MissingFieldError(ValidationError):
    """필수 필드 누락 예외"""

    def __init__(self, field: str):
        super().__init__(
            message=f"Missing required field: {field}", details={"field": field}
        )


# ==================== Resource Exceptions ====================


class ResourceNotFoundError(ApplicationError):
    """리소스를 찾을 수 없음 예외"""

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


class ResourceConflictError(ApplicationError):
    """리소스 충돌 예외"""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(
            message=message, code="RESOURCE_CONFLICT", status_code=409, details=details
        )


# ==================== Authorization Exceptions ====================


class AuthenticationError(ApplicationError):
    """인증 실패 예외"""

    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message, code="AUTHENTICATION_ERROR", status_code=401)


class AuthorizationError(ApplicationError):
    """권한 부족 예외"""

    def __init__(self, message: str = "Authorization failed"):
        super().__init__(message, code="AUTHORIZATION_ERROR", status_code=403)


class TokenExpiredError(AuthenticationError):
    """토큰 만료 예외"""

    def __init__(self):
        super().__init__(message="Token has expired")


class InvalidTokenError(AuthenticationError):
    """잘못된 토큰 예외"""

    def __init__(self):
        super().__init__(message="Invalid token")


# ==================== Business Logic Exceptions ====================


class BusinessLogicError(ApplicationError):
    """비즈니스 로직 예외"""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(
            message=message, code="BUSINESS_LOGIC_ERROR", status_code=422, details=details
        )


class OrderError(BusinessLogicError):
    """주문 관련 예외"""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message=f"Order error: {message}", details=details)


class InsufficientBalanceError(BusinessLogicError):
    """잔고 부족 예외"""

    def __init__(self, required: float, available: float):
        super().__init__(
            message="Insufficient balance",
            details={"required": required, "available": available},
        )


class PositionNotFoundError(ResourceNotFoundError):
    """포지션을 찾을 수 없음 예외"""

    def __init__(self, symbol: str, account_no: str):
        super().__init__(
            resource="Position", identifier=f"{account_no}:{symbol}"
        )


class StrategyError(BusinessLogicError):
    """전략 관련 예외"""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message=f"Strategy error: {message}", details=details)


class StrategyExecutionError(StrategyError):
    """전략 실행 실패 예외"""

    def __init__(self, strategy_id: int, message: str):
        super().__init__(
            message=f"Strategy execution failed: {message}",
            details={"strategy_id": strategy_id},
        )


# ==================== External Service Exceptions ====================


class ExternalServiceError(ApplicationError):
    """외부 서비스 오류 예외"""

    def __init__(
        self, service: str, message: str, details: dict[str, Any] | None = None
    ):
        super().__init__(
            message=f"{service} error: {message}",
            code="EXTERNAL_SERVICE_ERROR",
            status_code=502,
            details=details,
        )


class KISAPIServiceError(ExternalServiceError):
    """KIS API 서비스 오류 예외"""

    def __init__(self, message: str, error_code: str | None = None):
        super().__init__(
            service="KIS API", message=message, details={"error_code": error_code}
        )


class DatabaseError(ExternalServiceError):
    """데이터베이스 오류 예외"""

    def __init__(self, message: str):
        super().__init__(service="Database", message=message)


class CacheError(ExternalServiceError):
    """캐시 오류 예외"""

    def __init__(self, message: str):
        super().__init__(service="Cache", message=message)


# ==================== Rate Limit Exceptions ====================


class RateLimitExceededError(ApplicationError):
    """Rate Limit 초과 예외"""

    def __init__(self, retry_after: int | None = None):
        super().__init__(
            message="Rate limit exceeded",
            code="RATE_LIMIT_EXCEEDED",
            status_code=429,
            details={"retry_after": retry_after},
        )


# ==================== Timeout Exceptions ====================


class TimeoutError(ApplicationError):
    """타임아웃 예외"""

    def __init__(self, operation: str, timeout: int):
        super().__init__(
            message=f"Operation timed out: {operation}",
            code="TIMEOUT_ERROR",
            status_code=504,
            details={"operation": operation, "timeout": timeout},
        )


# ==================== Configuration Exceptions ====================


class ConfigurationError(ApplicationError):
    """설정 오류 예외"""

    def __init__(self, message: str):
        super().__init__(message, code="CONFIGURATION_ERROR", status_code=500)


class EnvironmentError(ConfigurationError):
    """환경 변수 오류 예외"""

    def __init__(self, variable: str):
        super().__init__(message=f"Missing or invalid environment variable: {variable}")
