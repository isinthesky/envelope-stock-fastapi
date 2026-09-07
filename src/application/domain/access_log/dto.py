# -*- coding: utf-8 -*-
"""
Access Log DTO - 접근 로그 응답 계약

기존 access_log_router가 dict로 조립하던 응답 구조를 필드명/순서/타입 그대로
DTO로 고정한다. 프론트(templates/page/access_logs.html)가 참조하는 키를
바꾸지 않는 것이 이 파일의 유일한 계약이다.
"""

from typing import Any

from src.application.common.dto import BaseDTO


class AccessLogItemDTO(BaseDTO):
    """접근 로그 1건 (accessed_at은 isoformat 문자열)"""

    id: int
    method: str
    path: str
    query_string: str | None = None
    ip_address: str
    user_agent: str | None = None
    referer: str | None = None
    status_code: int
    response_time_ms: int | None = None
    accessed_at: str | None = None
    country: str | None = None
    city: str | None = None


class AccessLogListDTO(BaseDTO):
    """접근 로그 목록 응답"""

    items: list[AccessLogItemDTO]
    count: int
    limit: int
    offset: int


class AccessLogStatsDTO(BaseDTO):
    """접근 통계 응답 (path_stats/ip_stats/hourly_stats는 repository dict 형태 유지)"""

    period_hours: int
    since: str
    total_requests: int
    unique_visitors: int
    path_stats: list[dict[str, Any]]
    ip_stats: list[dict[str, Any]]
    hourly_stats: list[dict[str, Any]]


class AccessLogUniqueIpsDTO(BaseDTO):
    """고유 IP 목록 응답"""

    period_hours: int
    since: str
    unique_ips: list[str]
    count: int


class AccessLogCleanupResultDTO(BaseDTO):
    """오래된 로그 정리 결과"""

    deleted_count: int
    before: str
