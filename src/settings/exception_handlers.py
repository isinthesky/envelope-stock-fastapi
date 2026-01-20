# -*- coding: utf-8 -*-
"""
Exception Handlers - 전역 예외 핸들러

모든 도메인 예외를 JSON 응답으로 변환하는 핸들러 모음.
앱 시작 시 register_exception_handlers()로 일괄 등록합니다.
"""

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.application.common.exceptions import ApplicationError

logger = logging.getLogger(__name__)


async def application_error_handler(request: Request, exc: ApplicationError) -> JSONResponse:
    """
    ApplicationError 핸들러

    모든 도메인 예외를 통일된 JSON 응답 포맷으로 변환합니다.

    Response format:
    {
        "success": false,
        "message": "...",
        "data": null,
        "error": {
            "code": "ERROR_CODE",
            "message": "...",
            "details": {...}
        }
    }
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
    # 첫 번째 에러 메시지를 대표 메시지로 사용
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
    디버그 모드에서만 상세 정보를 노출합니다.
    """
    from src.settings.config import get_settings

    settings = get_settings()

    logger.exception(
        "Unhandled exception: %s (path=%s)",
        str(exc),
        request.url.path,
    )

    detail = str(exc) if settings.debug else "An unexpected error occurred"

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
