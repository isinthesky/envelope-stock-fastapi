# -*- coding: utf-8 -*-
"""Redis 락 소유 토큰 기반 원자적 해제 테스트."""

import pytest

from src.adapters.cache.redis_client import RedisClient


class FakeRedisConnection:
    def __init__(self, result: int = 1, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[str, int, str, str]] = []

    async def eval(self, script: str, key_count: int, key: str, expected: str) -> int:
        self.calls.append((script, key_count, key, expected))
        if self.error:
            raise self.error
        return self.result


@pytest.mark.asyncio
async def test_compare_and_delete_uses_single_atomic_eval() -> None:
    client = RedisClient()
    connection = FakeRedisConnection(result=1)
    client.redis = connection  # type: ignore[assignment]

    deleted = await client.compare_and_delete("scan-lock", "owner-token")

    assert deleted is True
    assert len(connection.calls) == 1
    script, key_count, key, expected = connection.calls[0]
    assert "redis.call('get'" in script
    assert "redis.call('del'" in script
    assert (key_count, key, expected) == (1, "scan-lock", "owner-token")


@pytest.mark.asyncio
async def test_compare_and_delete_preserves_non_owner_lock() -> None:
    client = RedisClient()
    connection = FakeRedisConnection(result=0)
    client.redis = connection  # type: ignore[assignment]

    assert await client.compare_and_delete("scan-lock", "stale-token") is False


@pytest.mark.asyncio
async def test_compare_and_delete_cleanup_error_is_left_to_ttl() -> None:
    client = RedisClient()
    connection = FakeRedisConnection(error=ConnectionError("redis reset"))
    client.redis = connection  # type: ignore[assignment]

    assert await client.compare_and_delete("scan-lock", "owner-token") is False
