# -*- coding: utf-8 -*-
"""
Access Log Router 테스트

라우터가 AccessLogService만 호출하고, 응답 계약(프론트 access_logs.html이 참조하는 키)이
유지되는지 검증한다. 세션/Repository를 라우터가 직접 다루지 않는 것도 함께 확인한다.
"""

import pytest

import src.application.interface.api.access_log_router as access_log_router
from src.application.domain.access_log.dto import (
    AccessLogCleanupResultDTO,
    AccessLogItemDTO,
    AccessLogListDTO,
    AccessLogStatsDTO,
    AccessLogUniqueIpsDTO,
)


class _StubService:
    """AccessLogService 대역 - 호출 인자를 기록하고 고정 DTO를 반환한다."""

    def __init__(self) -> None:
        self.calls: dict[str, dict] = {}

    async def get_recent_logs(self, **kwargs):
        self.calls["get_recent_logs"] = kwargs
        return AccessLogListDTO(
            items=[
                AccessLogItemDTO(
                    id=1,
                    method="GET",
                    path="/page/",
                    query_string=None,
                    ip_address="1.2.3.4",
                    user_agent="UA",
                    referer=None,
                    status_code=200,
                    response_time_ms=12,
                    accessed_at="2026-09-08T00:00:00+00:00",
                    country=None,
                    city=None,
                )
            ],
            count=1,
            limit=kwargs["limit"],
            offset=kwargs["offset"],
        )

    async def get_stats(self, **kwargs):
        self.calls["get_stats"] = kwargs
        return AccessLogStatsDTO(
            period_hours=kwargs["hours"],
            since="2026-09-07T00:00:00+00:00",
            total_requests=10,
            unique_visitors=2,
            path_stats=[{"path": "/page/", "count": 7}],
            ip_stats=[{"ip": "1.2.3.4", "count": 7}],
            hourly_stats=[{"hour": "2026-09-08 00:00:00+00:00", "count": 3}],
        )

    async def get_unique_ips(self, **kwargs):
        self.calls["get_unique_ips"] = kwargs
        return AccessLogUniqueIpsDTO(
            period_hours=kwargs["hours"],
            since="2026-09-07T00:00:00+00:00",
            unique_ips=["1.2.3.4", "5.6.7.8"],
            count=2,
        )

    async def cleanup_old_logs(self, **kwargs):
        self.calls["cleanup_old_logs"] = kwargs
        return AccessLogCleanupResultDTO(deleted_count=5, before="2026-08-09T00:00:00+00:00")


@pytest.mark.asyncio
async def test_get_access_logs_preserves_item_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _StubService()
    monkeypatch.setattr(access_log_router, "AccessLogService", lambda: stub)

    response = await access_log_router.get_access_logs(
        limit=100, offset=0, path_filter=None, ip_filter=None, admin_access="127.0.0.1"
    )

    assert response.success is True
    payload = response.data.model_dump()
    assert set(payload) == {"items", "count", "limit", "offset"}
    assert set(payload["items"][0]) == {
        "id",
        "method",
        "path",
        "query_string",
        "ip_address",
        "user_agent",
        "referer",
        "status_code",
        "response_time_ms",
        "accessed_at",
        "country",
        "city",
    }
    assert stub.calls["get_recent_logs"] == {
        "limit": 100,
        "offset": 0,
        "path_filter": None,
        "ip_filter": None,
    }


@pytest.mark.asyncio
async def test_get_access_stats_preserves_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _StubService()
    monkeypatch.setattr(access_log_router, "AccessLogService", lambda: stub)

    response = await access_log_router.get_access_stats(hours=24, admin_access="127.0.0.1")

    payload = response.data.model_dump()
    assert set(payload) == {
        "period_hours",
        "since",
        "total_requests",
        "unique_visitors",
        "path_stats",
        "ip_stats",
        "hourly_stats",
    }
    assert payload["path_stats"][0].keys() == {"path", "count"}
    assert payload["ip_stats"][0].keys() == {"ip", "count"}
    assert stub.calls["get_stats"] == {"hours": 24}


@pytest.mark.asyncio
async def test_get_unique_ips_preserves_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _StubService()
    monkeypatch.setattr(access_log_router, "AccessLogService", lambda: stub)

    response = await access_log_router.get_unique_ips(hours=48, admin_access="127.0.0.1")

    payload = response.data.model_dump()
    assert set(payload) == {"period_hours", "since", "unique_ips", "count"}
    assert payload["unique_ips"] == ["1.2.3.4", "5.6.7.8"]
    assert stub.calls["get_unique_ips"] == {"hours": 48}


@pytest.mark.asyncio
async def test_cleanup_message_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _StubService()
    monkeypatch.setattr(access_log_router, "AccessLogService", lambda: stub)

    response = await access_log_router.cleanup_old_logs(days=30, admin_access="127.0.0.1")

    assert response.message == "5개의 오래된 로그가 삭제되었습니다."
    assert response.data.deleted_count == 5
    assert set(response.data.model_dump()) == {"deleted_count", "before"}
    assert stub.calls["cleanup_old_logs"] == {"days": 30}


def test_router_module_has_no_session_or_repository_import() -> None:
    """레이어 규칙 회귀 방지 - 라우터 모듈이 세션/Repository를 직접 참조하지 않는다."""
    source = open(access_log_router.__file__, encoding="utf-8").read()
    assert "get_async_session" not in source
    assert "AccessLogRepository" not in source
