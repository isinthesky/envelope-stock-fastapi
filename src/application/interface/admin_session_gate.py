# -*- coding: utf-8 -*-
"""
Admin Session Gate - 공개 경로 외 전체를 관리자 로그인 세션 뒤로 두는 ASGI 미들웨어

기본값이 거부(fail-closed)다: 아래 `PUBLIC_*` 목록에 없는 HTTP/WebSocket 경로는 전부 로그인 세션을
요구하므로, 새 라우터를 추가해도 자동으로 보호된다. 라우터 단위 `verify_admin_access`(IP 게이트 +
쓰기 CSRF 헤더)와 주문 API의 `require_admin_session`은 이 게이트 안쪽의 추가 방어선으로 그대로 둔다.

- 미로그인 HTML 페이지(GET /mypage/*, /ops*) → 303 /mypage/login/?next=<path>
- 미로그인 API/기타 → 401 JSON (ResponseDTO 에러 형식)
- 미로그인 WebSocket → 핸드셰이크 거부(403)
- 세션 조회 실패(Redis 장애 등) → 미로그인으로 취급
"""

import logging
from typing import Any
from urllib.parse import quote

from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse, RedirectResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from src.application.common.dependencies import ADMIN_SESSION_COOKIE, get_admin_auth_service

logger = logging.getLogger(__name__)

# 로그인 없이 접근 가능한 경로 (정확히 일치)
PUBLIC_EXACT_PATHS = frozenset(
    {
        "/health",  # 컨테이너 healthcheck
        "/page",
        "/mypage/login",
        "/mypage/login/",
        "/api/v1/admin-auth/login",
        "/api/v1/admin-auth/logout",
    }
)
# 로그인 없이 접근 가능한 경로 (접두사)
PUBLIC_PATH_PREFIXES = ("/page/", "/static/", "/api/v1/public/")
# 미로그인 시 JSON 대신 로그인 페이지로 보내는 HTML 경로 접두사
HTML_PATH_PREFIXES = ("/mypage", "/ops")
LOGIN_PATH = "/mypage/login/"


def is_public_path(path: str) -> bool:
    return path in PUBLIC_EXACT_PATHS or path.startswith(PUBLIC_PATH_PREFIXES)


def _wants_redirect(scope: Scope, path: str) -> bool:
    return scope.get("method") in ("GET", "HEAD") and path.startswith(HTML_PATH_PREFIXES)


class AdminSessionGateMiddleware:
    """공개 경로 외 모든 요청에 관리자 로그인 세션을 요구한다."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        path: str = scope["path"]
        if is_public_path(path) or scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return

        if await self._has_valid_session(scope):
            await self.app(scope, receive, send)
            return

        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return

        if _wants_redirect(scope, path):
            response: Any = RedirectResponse(
                url=f"{LOGIN_PATH}?next={quote(path, safe='')}", status_code=303
            )
        else:
            response = JSONResponse(
                status_code=401,
                content={
                    "success": False,
                    "message": "Admin login required",
                    "data": None,
                    "error": {
                        "code": "AUTHENTICATION_ERROR",
                        "message": "Admin login required",
                        "details": {},
                    },
                },
            )
        await response(scope, receive, send)

    async def _has_valid_session(self, scope: Scope) -> bool:
        token = HTTPConnection(scope).cookies.get(ADMIN_SESSION_COOKIE)
        if not token:
            return False
        # 테스트에서 FastAPI dependency_overrides로 주입한 서비스를 그대로 따른다.
        app = scope.get("app")
        overrides = getattr(app, "dependency_overrides", {}) or {}
        factory = overrides.get(get_admin_auth_service, get_admin_auth_service)
        try:
            service = await factory()
            return await service.get_session(token) is not None
        except Exception:
            logger.exception("[admin_session_gate] session lookup failed; treating as anonymous")
            return False
