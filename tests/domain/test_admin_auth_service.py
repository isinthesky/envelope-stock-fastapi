from typing import Any

import pytest

from src.application.common.exceptions import (
    AuthenticationError,
    RateLimitExceededError,
    ServiceUnavailableError,
)
from src.application.common.password_hash import hash_password
from src.application.domain.admin_auth.service import AdminAuthService
from src.settings.config import Settings

PASSWORD = "s3cret-pass-phrase"
PASSWORD_HASH = hash_password(PASSWORD)


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, Any] = {}
        self.ttls: dict[str, int] = {}
        self.fail_incr = False

    async def get(self, key: str, deserialize: bool = True) -> Any:
        return self.store.get(key)

    async def set(self, key: str, value: Any, ttl: int | None = None, **_: Any) -> bool:
        self.store[key] = value
        if ttl:
            self.ttls[key] = ttl
        return True

    async def delete(self, key: str) -> bool:
        return self.store.pop(key, None) is not None

    async def ttl(self, key: str) -> int:
        return self.ttls.get(key, -2)

    async def incr_with_ttl(self, key: str, ttl: int) -> int:
        if self.fail_incr:
            raise ConnectionError("down")
        self.store[key] = int(self.store.get(key) or 0) + 1
        if self.store[key] == 1:
            self.ttls[key] = ttl
        return self.store[key]


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "admin_username": "operator",
        "admin_password_hash": PASSWORD_HASH,
        "admin_login_max_failures": 3,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.mark.asyncio
async def test_login_creates_session_stored_by_token_hash() -> None:
    redis = FakeRedis()
    service = AdminAuthService(redis, _settings())  # type: ignore[arg-type]

    result = await service.login("operator", PASSWORD, "10.0.0.1")

    assert result.session.username == "operator"
    assert all(result.token not in key for key in redis.store)  # 원문 토큰은 저장하지 않음
    session = await service.get_session(result.token)
    assert session is not None and session.username == "operator"


@pytest.mark.asyncio
async def test_wrong_password_and_wrong_username_both_fail_generically() -> None:
    service = AdminAuthService(FakeRedis(), _settings())  # type: ignore[arg-type]

    with pytest.raises(AuthenticationError):
        await service.login("operator", "nope", "10.0.0.1")
    with pytest.raises(AuthenticationError):
        await service.login("intruder", PASSWORD, "10.0.0.1")


@pytest.mark.asyncio
async def test_lockout_after_max_failures_blocks_even_correct_password() -> None:
    service = AdminAuthService(FakeRedis(), _settings())  # type: ignore[arg-type]

    for _ in range(3):
        with pytest.raises(AuthenticationError):
            await service.login("operator", "nope", "10.0.0.9")

    with pytest.raises(RateLimitExceededError):
        await service.login("operator", PASSWORD, "10.0.0.9")
    # 다른 IP는 영향 없음
    assert (await service.login("operator", PASSWORD, "10.0.0.2")).token


@pytest.mark.asyncio
async def test_success_resets_failure_counter() -> None:
    redis = FakeRedis()
    service = AdminAuthService(redis, _settings())  # type: ignore[arg-type]

    for _ in range(2):
        with pytest.raises(AuthenticationError):
            await service.login("operator", "nope", "10.0.0.3")
    await service.login("operator", PASSWORD, "10.0.0.3")

    assert "admin_login_fail:10.0.0.3" not in redis.store


@pytest.mark.asyncio
async def test_unconfigured_login_is_fail_closed() -> None:
    service = AdminAuthService(FakeRedis(), _settings(admin_password_hash=""))  # type: ignore[arg-type]

    with pytest.raises(ServiceUnavailableError):
        await service.login("operator", PASSWORD, "10.0.0.1")
    assert await service.get_session("anything") is None


@pytest.mark.asyncio
async def test_redis_failure_on_failure_counter_is_fail_closed() -> None:
    redis = FakeRedis()
    redis.fail_incr = True
    service = AdminAuthService(redis, _settings())  # type: ignore[arg-type]

    with pytest.raises(ServiceUnavailableError):
        await service.login("operator", "nope", "10.0.0.1")


@pytest.mark.asyncio
async def test_logout_and_credential_rotation_invalidate_sessions() -> None:
    redis = FakeRedis()
    service = AdminAuthService(redis, _settings())  # type: ignore[arg-type]
    first = await service.login("operator", PASSWORD, "10.0.0.1")
    second = await service.login("operator", PASSWORD, "10.0.0.1")

    await service.logout(first.token)
    assert await service.get_session(first.token) is None
    assert await service.get_session(second.token) is not None

    rotated = AdminAuthService(redis, _settings(admin_password_hash=hash_password("new-pass-123456")))  # type: ignore[arg-type]
    assert await rotated.get_session(second.token) is None
