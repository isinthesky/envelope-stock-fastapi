"""주문 페이지/주문 API 로그인 경계 회귀 테스트.

IP 게이트(verify_admin_access)는 허용으로 override하고, 그 위의 로그인 세션 게이트만 검증한다.
"""

from typing import Any

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from src.application.common.dependencies import (
    ADMIN_SESSION_COOKIE,
    get_admin_auth_service,
    verify_admin_access,
)
from src.application.common.password_hash import hash_password
from src.application.domain.admin_auth.service import AdminAuthService
from src.application.interface.page.admin_login_page_router import safe_next_path
from src.main import app
from src.settings.config import Settings
from tests.domain.test_admin_auth_service import FakeRedis

PASSWORD = "boundary-pass-phrase"
SETTINGS = Settings(
    _env_file=None, admin_username="operator", admin_password_hash=hash_password(PASSWORD)
)
CSRF = {"X-Requested-With": "XMLHttpRequest"}


async def _allow_ip(request: Request) -> str:
    return "127.0.0.1"


@pytest.fixture()
def client() -> Any:
    service = AdminAuthService(FakeRedis(), SETTINGS)  # type: ignore[arg-type]

    async def _service() -> AdminAuthService:
        return service

    app.dependency_overrides[verify_admin_access] = _allow_ip
    app.dependency_overrides[get_admin_auth_service] = _service
    try:
        # Secure 쿠키(ADMIN_SESSION_COOKIE_SECURE=true) 환경에서도 동작하도록 https로 요청한다.
        yield TestClient(app, base_url="https://testserver", raise_server_exceptions=False)
    finally:
        app.dependency_overrides.clear()


def _login(client: TestClient, password: str = PASSWORD) -> Any:
    return client.post(
        "/api/v1/admin-auth/login",
        json={"username": "operator", "password": password},
        headers=CSRF,
    )


def test_order_page_redirects_to_login_when_anonymous(client: TestClient) -> None:
    response = client.get("/mypage/order/", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/mypage/login/?next=")


def test_order_api_requires_login_for_every_method(client: TestClient) -> None:
    assert client.get("/api/v1/orders").status_code == 401
    assert client.get("/api/v1/orders/abc").status_code == 401
    created = client.post(
        "/api/v1/orders",
        json={"symbol": "005930", "order_type": "buy", "price_type": "market", "quantity": 1},
        headers=CSRF,
    )
    assert created.status_code == 401


def test_login_page_renders_without_session(client: TestClient) -> None:
    response = client.get("/mypage/login/?next=/mypage/order/")

    assert response.status_code == 200
    assert "관리자 로그인" in response.text


def test_wrong_password_returns_401_without_cookie(client: TestClient) -> None:
    response = _login(client, "wrong")

    assert response.status_code == 401
    assert ADMIN_SESSION_COOKIE not in response.cookies


def test_login_sets_hardened_cookie_and_opens_order_page(client: TestClient) -> None:
    response = _login(client)

    assert response.status_code == 200
    set_cookie = response.headers["set-cookie"].lower()
    assert "httponly" in set_cookie and "samesite=strict" in set_cookie
    assert "token" not in response.json()["data"]  # 토큰은 본문에 싣지 않음

    page = client.get("/mypage/order/", follow_redirects=False)
    assert page.status_code == 200
    assert "로그아웃" in page.text and "operator" in page.text
    assert client.get("/api/v1/admin-auth/me").status_code == 200


def test_logout_revokes_session(client: TestClient) -> None:
    _login(client)
    assert client.post("/api/v1/admin-auth/logout", headers=CSRF).status_code == 200

    assert client.get("/mypage/order/", follow_redirects=False).status_code == 303
    assert client.get("/api/v1/admin-auth/me").status_code == 401


def test_forged_cookie_is_rejected(client: TestClient) -> None:
    client.cookies.set(ADMIN_SESSION_COOKIE, "forged-token")

    assert client.get("/api/v1/orders").status_code == 401


def test_login_and_order_still_ip_gated_without_override() -> None:
    # override 없이: TestClient 호스트("testclient")는 IP allowlist를 통과하지 못한다.
    raw = TestClient(app, raise_server_exceptions=False)

    assert (
        raw.post(
            "/api/v1/admin-auth/login", json={"username": "a", "password": "b"}, headers=CSRF
        ).status_code
        == 403
    )
    assert raw.get("/mypage/login/").status_code == 403


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("/mypage/account/", "/mypage/account/"),
        (None, "/mypage/order/"),
        ("https://evil.example/", "/mypage/order/"),
        ("//evil.example/mypage/", "/mypage/order/"),
        ("/mypage/..//evil", "/mypage/order/"),
        ("/mypage/\\evil", "/mypage/order/"),
        ("/mypage/login/", "/mypage/order/"),
        ("/ops", "/ops"),
        ("/ops/../x", "/mypage/order/"),
    ],
)
def test_safe_next_path_blocks_open_redirect(raw: str | None, expected: str) -> None:
    assert safe_next_path(raw) == expected


# ==================== 전역 세션 게이트 (AdminSessionGateMiddleware) ====================


@pytest.mark.parametrize("path", ["/mypage/", "/mypage/account/", "/ops", "/ops/"])
def test_gate_redirects_anonymous_admin_pages_to_login(client: TestClient, path: str) -> None:
    response = client.get(path, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/mypage/login/?next=")


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/api/v1/accounts/balance",
        "/api/v1/strategies",
        "/api/v1/ops/summary",
        "/api/v1/auth/token/status",
        "/api/v1/access-logs",
        "/api/v1/backtest/presets",
        "/api/v1/does-not-exist",
    ],
)
def test_gate_rejects_anonymous_api_with_401(client: TestClient, path: str) -> None:
    response = client.get(path)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_ERROR"


def test_gate_rejects_anonymous_websocket(client: TestClient) -> None:
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/realtime"):
            pass


def test_gate_lets_logged_in_admin_reach_admin_pages(client: TestClient) -> None:
    _login(client)

    response = client.get("/mypage/account/", follow_redirects=False)

    assert response.status_code == 200


@pytest.mark.parametrize(
    ("path", "public"),
    [
        ("/health", True),
        ("/page", True),
        ("/page/scan/", True),
        ("/static/js/pages/public_strategy_scan.js", True),
        ("/api/v1/public/strategies/scan-capabilities", True),
        ("/mypage/login/", True),
        ("/api/v1/admin-auth/login", True),
        ("/api/v1/admin-auth/me", False),
        ("/pages", False),
        ("/mypage/login-bypass", False),
        ("/api/v1/publicx", False),
        ("/mypage/order/", False),
    ],
)
def test_public_path_allowlist_is_exact(path: str, public: bool) -> None:
    from src.application.interface.admin_session_gate import is_public_path

    assert is_public_path(path) is public
