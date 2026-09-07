# -*- coding: utf-8 -*-
"""접근 로그 미들웨어 - IP 기록이 admin 판정과 동일한 규칙을 쓰는지 검증"""

from typing import Any

import pytest
from starlette.requests import Request

from src.application.common import dependencies
from src.application.common.middleware import access_logging
from src.application.common.middleware.access_logging import AccessLoggingMiddleware
from src.settings.config import Settings


async def _app(scope: Any, receive: Any, send: Any) -> None:  # pragma: no cover - 더미 ASGI 앱
    raise NotImplementedError


def _request(client: tuple[str, int], headers: list[tuple[bytes, bytes]]) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/page/",
            "headers": headers,
            "client": client,
        }
    )


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """실제 .env에 의존하지 않도록 기본값 Settings를 주입한다."""
    fixed = Settings(_env_file=None)
    monkeypatch.setattr(access_logging, "get_settings", lambda: fixed)
    return fixed


def test_forged_xff_from_untrusted_client_is_not_logged(settings: Settings) -> None:
    """신뢰하지 않는 직접 접속이 보낸 X-Forwarded-For로 감사 로그를 위조할 수 없다."""
    middleware = AccessLoggingMiddleware(_app)
    request = _request(("182.230.237.24", 51234), [(b"x-forwarded-for", b"1.2.3.4")])

    assert middleware._get_client_ip(request) == "182.230.237.24"


def test_forged_real_ip_from_untrusted_client_is_not_logged(settings: Settings) -> None:
    middleware = AccessLoggingMiddleware(_app)
    request = _request(("182.230.237.24", 51234), [(b"x-real-ip", b"1.2.3.4")])

    assert middleware._get_client_ip(request) == "182.230.237.24"


def test_trusted_proxy_xff_is_logged(settings: Settings) -> None:
    """신뢰 프록시(loopback) 경유 요청은 XFF의 실제 클라이언트를 기록한다."""
    assert settings.trusted_proxy_ips == ["127.0.0.0/8", "::1/128"]

    middleware = AccessLoggingMiddleware(_app)
    request = _request(("127.0.0.1", 51234), [(b"x-forwarded-for", b"6.6.6.6, 5.5.5.5")])

    assert middleware._get_client_ip(request) == "5.5.5.5"


def test_middleware_ip_matches_admin_gate_ip(settings: Settings) -> None:
    """감사 로그 IP와 admin 판정 IP가 같은 값이어야 한다(두 경로 불일치 회귀 방지)."""
    middleware = AccessLoggingMiddleware(_app)
    request = _request(("182.230.237.24", 51234), [(b"x-forwarded-for", b"127.0.0.1")])

    assert middleware._get_client_ip(request) == dependencies.get_client_ip(
        request, settings.trusted_proxy_ips
    )


def test_dependencies_reexports_stay_available() -> None:
    """하위호환: dependencies에서 get_client_ip/_is_ip_allowed import 경로가 유지된다."""
    from src.application.common.client_ip import get_client_ip, is_ip_allowed

    assert dependencies.get_client_ip is get_client_ip
    assert dependencies._is_ip_allowed is is_ip_allowed
