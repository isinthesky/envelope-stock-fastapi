# -*- coding: utf-8 -*-
"""client_ip 공통 유틸 - 신뢰 프록시/스푸핑 차단 규칙 테스트"""

from typing import Any

from starlette.requests import Request

from src.application.common.client_ip import extract_client_ip, get_client_ip, is_ip_allowed

TRUSTED = ["127.0.0.0/8", "::1/128"]


def _request(client: tuple[str, int] | None, headers: list[tuple[bytes, bytes]]) -> Request:
    scope: dict[str, Any] = {
        "type": "http",
        "method": "GET",
        "path": "/page/",
        "headers": headers,
    }
    if client is not None:
        scope["client"] = client
    return Request(scope)


def test_untrusted_direct_connection_ignores_forged_xff() -> None:
    """신뢰하지 않는 직접 접속의 위조 X-Forwarded-For는 무시한다."""
    request = _request(("182.230.237.24", 51234), [(b"x-forwarded-for", b"1.2.3.4")])

    assert get_client_ip(request, TRUSTED) == "182.230.237.24"


def test_untrusted_direct_connection_ignores_forged_real_ip() -> None:
    """신뢰하지 않는 직접 접속의 위조 X-Real-IP도 무시한다."""
    request = _request(("182.230.237.24", 51234), [(b"x-real-ip", b"1.2.3.4")])

    assert get_client_ip(request, TRUSTED) == "182.230.237.24"


def test_trusted_proxy_uses_rightmost_untrusted_hop() -> None:
    """신뢰 프록시 경유 시 오른쪽(가장 가까운) 미신뢰 hop을 클라이언트로 본다."""
    request = _request(("127.0.0.1", 51234), [(b"x-forwarded-for", b"6.6.6.6, 5.5.5.5")])

    assert get_client_ip(request, TRUSTED) == "5.5.5.5"


def test_trusted_proxy_falls_back_to_real_ip() -> None:
    request = _request(("127.0.0.1", 51234), [(b"x-real-ip", b"5.5.5.5")])

    assert get_client_ip(request, TRUSTED) == "5.5.5.5"


def test_trusted_proxy_with_all_trusted_hops_uses_outermost() -> None:
    """모든 hop이 신뢰 프록시(비정상)면 가장 바깥 값을 사용한다."""
    request = _request(("127.0.0.1", 51234), [(b"x-forwarded-for", b"127.0.0.2, 127.0.0.3")])

    assert get_client_ip(request, TRUSTED) == "127.0.0.2"


def test_empty_trusted_list_falls_back_to_direct_ip() -> None:
    """로컬 개발/설정 미비: 신뢰 목록이 비면 헤더를 전혀 신뢰하지 않는다."""
    request = _request(("127.0.0.1", 51234), [(b"x-forwarded-for", b"1.2.3.4")])

    assert get_client_ip(request, []) == "127.0.0.1"
    assert get_client_ip(request, None) == "127.0.0.1"
    assert get_client_ip(request) == "127.0.0.1"


def test_empty_trusted_list_ignores_real_ip_header() -> None:
    """신뢰 목록이 비면 X-Real-IP도 무시하고 직접 연결 IP를 쓴다."""
    request = _request(("127.0.0.1", 51234), [(b"x-real-ip", b"1.2.3.4")])

    assert get_client_ip(request, []) == "127.0.0.1"


def test_missing_client_returns_unknown() -> None:
    request = _request(None, [(b"x-forwarded-for", b"1.2.3.4")])

    assert get_client_ip(request, TRUSTED) == "unknown"


def test_non_ip_direct_host_is_untrusted() -> None:
    """TestClient의 'testclient' 같은 비-IP host는 신뢰하지 않는다."""
    assert extract_client_ip("testclient", "1.2.3.4", None, TRUSTED) == "testclient"


def test_extract_client_ip_without_direct_ip_returns_unknown() -> None:
    assert extract_client_ip(None, "1.2.3.4", "1.2.3.4", TRUSTED) == "unknown"


def test_is_ip_allowed_cidr_and_unknown() -> None:
    assert is_ip_allowed("172.22.0.1", ["172.16.0.0/12"])
    assert not is_ip_allowed("8.8.8.8", ["172.16.0.0/12"])
    assert not is_ip_allowed("unknown", ["0.0.0.0/0"])


def test_is_ip_allowed_ignores_malformed_entries() -> None:
    """허용 목록에 잘못된 값이 섞여도 예외 없이 나머지를 평가한다."""
    assert is_ip_allowed("127.0.0.1", ["not-an-ip", "127.0.0.1"])
    assert not is_ip_allowed("not-an-ip", ["127.0.0.1"])
