# -*- coding: utf-8 -*-
"""
Client IP - 신뢰 프록시 기반 클라이언트 IP 추출 (단일 진실 공급원)

관리자 IP 검증(verify_admin_access), 공개 rate limit(public_strategy_router),
접근 로그 미들웨어(AccessLoggingMiddleware), WebSocket 접근 제어가
모두 이 모듈의 동일한 규칙을 사용합니다.

의존성: stdlib(ipaddress) + starlette 타입만 사용합니다.
adapters/domain/interface를 import하지 않으므로 순환 import가 발생하지 않습니다.
"""

import ipaddress

from starlette.requests import HTTPConnection

__all__ = ["extract_client_ip", "get_client_ip", "is_ip_allowed"]


def is_ip_allowed(client_ip: str, allowed_ips: list[str]) -> bool:
    """IP가 허용 목록에 있는지 확인 (CIDR 지원)"""
    if client_ip == "unknown":
        return False

    try:
        client_addr = ipaddress.ip_address(client_ip)
    except ValueError:
        return False

    for allowed in allowed_ips:
        try:
            if "/" in allowed:
                network = ipaddress.ip_network(allowed, strict=False)
                if client_addr in network:
                    return True
            else:
                if client_addr == ipaddress.ip_address(allowed):
                    return True
        except ValueError:
            continue

    return False


def extract_client_ip(
    direct_ip: str | None,
    forwarded_for: str | None,
    real_ip: str | None,
    trusted_proxy_ips: list[str] | None = None,
) -> str:
    """신뢰 프록시 규칙에 따라 클라이언트 IP를 결정한다.

    프록시 헤더(X-Forwarded-For/X-Real-IP)는 직접 연결 IP가
    신뢰할 수 있는 내부 네트워크(reverse proxy 등)인 경우에만 참조합니다.
    신뢰하지 않는 직접 접속의 위조 헤더는 무시됩니다.

    X-Forwarded-For는 프록시가 append하므로(nginx $proxy_add_x_forwarded_for),
    client가 왼쪽에 위조 값을 끼워넣을 수 있습니다. 따라서 왼쪽이 아니라
    오른쪽(가장 가까운 hop)부터 신뢰 프록시가 아닌 첫 IP(마지막 미신뢰 hop)를
    실제 클라이언트로 취급해, 위조를 통한 IP 스푸핑(관리자 허용 IP/공개 쿨다운
    우회, 접근 로그 위조)을 차단합니다.
    """
    if not direct_ip:
        return "unknown"

    trusted = trusted_proxy_ips or []

    # 직접 연결 IP가 신뢰 가능한 프록시인 경우에만 헤더 참조
    try:
        addr = ipaddress.ip_address(direct_ip)
        is_trusted = is_ip_allowed(str(addr), trusted)
    except ValueError:
        is_trusted = False

    if is_trusted:
        if forwarded_for:
            hops = [p.strip() for p in forwarded_for.split(",") if p.strip()]
            # 오른쪽부터 신뢰 프록시가 아닌 첫 hop = 실제 클라이언트
            for candidate in reversed(hops):
                if not is_ip_allowed(candidate, trusted):
                    return candidate
            # 모든 hop이 신뢰 프록시(비정상)면 가장 바깥 값 사용
            if hops:
                return hops[0]
        # X-Real-IP는 프록시가 overwrite로 설정하는 단일 값(single-proxy 전제)
        if real_ip:
            return real_ip

    return direct_ip


def get_client_ip(connection: HTTPConnection, trusted_proxy_ips: list[str] | None = None) -> str:
    """HTTP 요청/WebSocket 연결에서 클라이언트 IP 추출

    starlette HTTPConnection(= fastapi.Request / starlette.Request / WebSocket의
    공통 조상)을 받으므로 라우터·미들웨어·WebSocket에서 동일하게 사용합니다.
    """
    return extract_client_ip(
        direct_ip=connection.client.host if connection.client else None,
        forwarded_for=connection.headers.get("x-forwarded-for"),
        real_ip=connection.headers.get("x-real-ip"),
        trusted_proxy_ips=trusted_proxy_ips,
    )
