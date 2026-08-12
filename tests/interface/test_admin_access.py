import pytest
from fastapi import Request

from src.application.common.dependencies import _is_ip_allowed, get_client_ip, verify_admin_access
from src.application.common.exceptions import AuthorizationError
from src.settings.config import Settings


def test_admin_allowed_ips_default_is_localhost_only() -> None:
    settings = Settings(_env_file=None)

    assert settings.admin_allowed_ips == ["127.0.0.1", "::1"]
    assert "172.16.0.0/12" not in settings.admin_allowed_ips


def test_is_ip_allowed_accepts_current_docker_bridge_ip() -> None:
    assert _is_ip_allowed("172.22.0.1", ["127.0.0.1", "::1", "172.16.0.0/12"])


def test_is_ip_allowed_rejects_non_private_ip() -> None:
    assert not _is_ip_allowed("8.8.8.8", ["127.0.0.1", "::1", "172.16.0.0/12"])


def test_get_client_ip_ignores_xff_from_untrusted_docker_bridge() -> None:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/ops",
            "headers": [(b"x-forwarded-for", b"8.8.8.8")],
            "client": ("172.22.0.1", 12345),
        }
    )

    assert get_client_ip(request, ["127.0.0.0/8", "::1/128"]) == "172.22.0.1"


def test_get_client_ip_accepts_xff_from_trusted_proxy() -> None:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/ops",
            "headers": [(b"x-forwarded-for", b"8.8.8.8, 127.0.0.1")],
            "client": ("127.0.0.1", 12345),
        }
    )

    assert get_client_ip(request, ["127.0.0.0/8", "::1/128"]) == "8.8.8.8"


def test_get_client_ip_ignores_forged_leftmost_xff_from_trusted_proxy() -> None:
    # 프록시가 실제 IP(5.5.5.5)를 append하고, client가 왼쪽에 위조값(6.6.6.6)을 끼워넣은 상황.
    # 왼쪽 위조가 아니라 오른쪽의 마지막 미신뢰 hop을 취해야 한다.
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/ops",
            "headers": [(b"x-forwarded-for", b"6.6.6.6, 5.5.5.5")],
            "client": ("127.0.0.1", 12345),
        }
    )

    assert get_client_ip(request, ["127.0.0.0/8", "::1/128"]) == "5.5.5.5"


def test_get_client_ip_spoofed_admin_ip_does_not_bypass_allowlist() -> None:
    # client가 XFF 왼쪽에 허용 IP(127.0.0.1)를 위조로 넣어도 관리자 우회 불가.
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/strategies/universe",
            "headers": [(b"x-forwarded-for", b"127.0.0.1, 9.9.9.9")],
            "client": ("127.0.0.1", 12345),
        }
    )

    assert get_client_ip(request, ["127.0.0.0/8", "::1/128"]) == "9.9.9.9"


def _request(method: str, headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": "/api/v1/orders",
            "headers": headers or [],
            "client": ("127.0.0.1", 12345),
        }
    )


@pytest.mark.asyncio
async def test_admin_write_request_requires_csrf_guard_header() -> None:
    with pytest.raises(AuthorizationError):
        await verify_admin_access(_request("POST"))


@pytest.mark.asyncio
async def test_admin_write_request_accepts_csrf_guard_header() -> None:
    client_ip = await verify_admin_access(
        _request("POST", [(b"x-requested-with", b"XMLHttpRequest")])
    )

    assert client_ip == "127.0.0.1"


@pytest.mark.asyncio
async def test_admin_read_request_does_not_require_csrf_guard_header() -> None:
    client_ip = await verify_admin_access(_request("GET"))

    assert client_ip == "127.0.0.1"
