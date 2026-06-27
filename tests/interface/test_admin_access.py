import pytest
from fastapi import Request

from src.application.common.dependencies import _get_client_ip, _is_ip_allowed, verify_admin_access
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

    assert _get_client_ip(request, ["127.0.0.0/8", "::1/128"]) == "172.22.0.1"


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

    assert _get_client_ip(request, ["127.0.0.0/8", "::1/128"]) == "8.8.8.8"


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
