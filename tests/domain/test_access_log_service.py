# -*- coding: utf-8 -*-
"""
AccessLogService 테스트

`@transaction`은 두 번째 positional 인자가 AsyncSession일 때만 세션 소유권을 넘기므로,
DB 없이 검증하려면 `functools.wraps`가 남긴 `__wrapped__`로 원본 함수를 직접 호출한다.
여기서는 DTO 매핑/슬라이싱/상위 N 규칙만 검증한다(쿼리 자체는 repository 책임).
"""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import src.application.domain.access_log.service as service_module
from src.application.domain.access_log.service import (
    HOURLY_STATS_LIMIT,
    TOP_STATS_LIMIT,
    AccessLogService,
)


class _FakeSession:
    """서비스에 명시적으로 넘기는 더미 세션 (repository를 대역으로 바꾸므로 사용되지 않는다)"""


def _log(idx: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=idx,
        method="GET",
        path="/page/",
        query_string=None,
        ip_address="1.2.3.4",
        user_agent="UA",
        referer=None,
        status_code=200,
        response_time_ms=5,
        accessed_at=datetime(2026, 9, 8, tzinfo=timezone.utc),
        country=None,
        city=None,
    )


class _FakeRepo:
    """AccessLogRepository 대역 - 호출 인자를 기록한다."""

    def __init__(self) -> None:
        self.hourly = [{"hour": str(i), "count": i} for i in range(40)]
        self.calls: dict[str, dict] = {}

    async def get_recent_logs(self, **kwargs):
        self.calls["get_recent_logs"] = kwargs
        return [_log(1), _log(2)]

    async def get_total_count(self, **kwargs):
        return 99

    async def get_unique_ips(self, **kwargs):
        self.calls["get_unique_ips"] = kwargs
        return ["1.2.3.4", "5.6.7.8"]

    async def get_path_stats(self, **kwargs):
        self.calls["get_path_stats"] = kwargs
        return [{"path": "/page/", "count": 9}]

    async def get_ip_stats(self, **kwargs):
        self.calls["get_ip_stats"] = kwargs
        return [{"ip": "1.2.3.4", "count": 9}]

    async def get_hourly_stats(self, **kwargs):
        return self.hourly

    async def delete_old_logs(self, **kwargs):
        self.calls["delete_old_logs"] = kwargs
        return 7


@pytest.fixture
def fake_repo(monkeypatch: pytest.MonkeyPatch) -> _FakeRepo:
    repo = _FakeRepo()
    monkeypatch.setattr(service_module, "AccessLogRepository", lambda: repo)
    return repo


@pytest.mark.asyncio
async def test_stats_truncates_hourly_and_uses_top_limit(fake_repo: _FakeRepo) -> None:
    raw = AccessLogService.get_stats.__wrapped__
    result = await raw(AccessLogService(), _FakeSession(), hours=24)

    assert len(result.hourly_stats) == HOURLY_STATS_LIMIT == 24
    assert result.unique_visitors == 2
    assert result.total_requests == 99
    assert result.period_hours == 24
    assert fake_repo.calls["get_path_stats"]["limit"] == TOP_STATS_LIMIT == 10
    assert fake_repo.calls["get_ip_stats"]["limit"] == TOP_STATS_LIMIT


@pytest.mark.asyncio
async def test_recent_logs_maps_accessed_at_to_isoformat(fake_repo: _FakeRepo) -> None:
    raw = AccessLogService.get_recent_logs.__wrapped__
    result = await raw(AccessLogService(), _FakeSession(), limit=10, offset=0)

    assert result.count == 2
    assert result.limit == 10
    assert result.offset == 0
    assert result.items[0].accessed_at == "2026-09-08T00:00:00+00:00"
    assert fake_repo.calls["get_recent_logs"]["limit"] == 10


@pytest.mark.asyncio
async def test_unique_ips_counts_repository_result(fake_repo: _FakeRepo) -> None:
    raw = AccessLogService.get_unique_ips.__wrapped__
    result = await raw(AccessLogService(), _FakeSession(), hours=48)

    assert result.period_hours == 48
    assert result.unique_ips == ["1.2.3.4", "5.6.7.8"]
    assert result.count == 2


@pytest.mark.asyncio
async def test_cleanup_returns_repository_deleted_count(fake_repo: _FakeRepo) -> None:
    raw = AccessLogService.cleanup_old_logs.__wrapped__
    result = await raw(AccessLogService(), _FakeSession(), days=30)

    assert result.deleted_count == 7
    assert "before" in fake_repo.calls["delete_old_logs"]
