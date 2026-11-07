# -*- coding: utf-8 -*-
"""
Admin Auth Router - 관리자 ID/PW 로그인/로그아웃 API

모든 엔드포인트는 IP allowlist + 쓰기 메서드 CSRF 헤더(`AdminAccessDep`)를 먼저 통과해야 한다.
세션 토큰은 HttpOnly/SameSite=Strict 쿠키로만 전달하고 응답 본문에는 싣지 않는다.
"""

from fastapi import APIRouter, Request, Response

from src.application.common.dependencies import (
    ADMIN_SESSION_COOKIE,
    AdminAccessDep,
    AdminAuthServiceDep,
    AdminSessionDep,
)
from src.application.common.dto import ResponseDTO
from src.application.domain.admin_auth.dto import AdminLoginRequestDTO, AdminSessionDTO
from src.settings.config import get_settings

router = APIRouter(prefix="/api/v1/admin-auth", tags=["AdminAuth"])


@router.post("/login", response_model=ResponseDTO[AdminSessionDTO])
async def login(
    payload: AdminLoginRequestDTO,
    response: Response,
    client_ip: AdminAccessDep,
    service: AdminAuthServiceDep,
) -> ResponseDTO[AdminSessionDTO]:
    """아이디/비밀번호 검증 후 세션 쿠키 발급"""
    result = await service.login(payload.username, payload.password, client_ip)

    settings = get_settings()
    response.set_cookie(
        key=ADMIN_SESSION_COOKIE,
        value=result.token,
        max_age=settings.admin_session_ttl_seconds,
        httponly=True,
        secure=settings.admin_session_cookie_secure,
        samesite="strict",
        path="/",
    )
    return ResponseDTO.success_response(result.session, "Login succeeded")


@router.post("/logout", response_model=ResponseDTO[None])
async def logout(
    request: Request,
    response: Response,
    admin_access: AdminAccessDep,
    service: AdminAuthServiceDep,
) -> ResponseDTO[None]:
    """세션 폐기 + 쿠키 삭제 (미로그인 상태여도 성공)"""
    _ = admin_access
    token = request.cookies.get(ADMIN_SESSION_COOKIE)
    if token:
        await service.logout(token)
    response.delete_cookie(key=ADMIN_SESSION_COOKIE, path="/")
    return ResponseDTO.success_response(None, "Logged out")


@router.get("/me", response_model=ResponseDTO[AdminSessionDTO])
async def me(
    admin_access: AdminAccessDep, session: AdminSessionDep
) -> ResponseDTO[AdminSessionDTO]:
    """현재 로그인 세션 조회 (미로그인 시 401)"""
    _ = admin_access
    return ResponseDTO.success_response(session, "Session active")
