# -*- coding: utf-8 -*-
"""
Admin Auth Service - 관리자 ID/PW 로그인과 Redis 세션 관리

- 계정: 단일 운영자 계정(`ADMIN_USERNAME` + `ADMIN_PASSWORD_HASH`). 미설정이면 로그인 비활성(fail-closed).
- 세션: 랜덤 토큰을 쿠키로 내리고, Redis에는 토큰의 SHA-256만 키로 저장한다(Redis 덤프 유출 시 재사용 불가).
  TTL은 절대 만료(슬라이딩 연장 없음).
- 무차별 대입 방어: IP별 고정 윈도우 실패 카운터. 한도 도달 시 비밀번호를 검증하지 않고 429.
- Redis 장애: 로그인/실패 집계는 503, 세션 조회는 미인증으로 취급(fail-closed).
"""

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone

from src.adapters.cache.redis_client import RedisClient
from src.application.common.exceptions import (
    AuthenticationError,
    RateLimitExceededError,
    ServiceUnavailableError,
)
from src.application.common.password_hash import hash_password, verify_password
from src.application.domain.admin_auth.dto import AdminLoginResultDTO, AdminSessionDTO
from src.settings.config import Settings, get_settings

logger = logging.getLogger(__name__)

SESSION_KEY_PREFIX = "admin_session:"
LOGIN_FAIL_KEY_PREFIX = "admin_login_fail:"

# 아이디 불일치 시에도 동일한 scrypt 비용을 치르게 해 타이밍으로 아이디를 추측하지 못하게 한다.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def _session_key(token: str) -> str:
    return SESSION_KEY_PREFIX + hashlib.sha256(token.encode("utf-8")).hexdigest()


def _credential_fingerprint(settings: Settings) -> str:
    """아이디/비밀번호 해시가 바뀌면 달라지는 값. 세션에 저장해 자격증명 교체 시 기존 세션을 무효화한다."""
    raw = f"{settings.admin_username}\n{settings.admin_password_hash}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class AdminAuthService:
    """관리자 로그인/세션 유즈케이스"""

    def __init__(self, redis: RedisClient, settings: Settings | None = None) -> None:
        self._redis = redis
        self._settings = settings or get_settings()

    @property
    def is_configured(self) -> bool:
        return bool(self._settings.admin_username and self._settings.admin_password_hash)

    async def login(self, username: str, password: str, client_ip: str) -> AdminLoginResultDTO:
        if not self.is_configured:
            raise ServiceUnavailableError("Admin login is not configured")

        fail_key = LOGIN_FAIL_KEY_PREFIX + client_ip
        failures = await self._redis.get(fail_key)
        if isinstance(failures, int) and failures >= self._settings.admin_login_max_failures:
            retry_after = await self._redis.ttl(fail_key)
            logger.warning("[admin_auth] login locked out ip=%s", client_ip)
            raise RateLimitExceededError(retry_after=retry_after if retry_after > 0 else None)

        username_ok = hmac.compare_digest(
            username.encode("utf-8"), self._settings.admin_username.encode("utf-8")
        )
        stored_hash = self._settings.admin_password_hash if username_ok else _DUMMY_HASH
        password_ok = verify_password(password, stored_hash)

        if not (username_ok and password_ok):
            try:
                count = await self._redis.incr_with_ttl(
                    fail_key, self._settings.admin_login_lockout_seconds
                )
            except Exception as exc:
                raise ServiceUnavailableError("Login temporarily unavailable") from exc
            logger.warning("[admin_auth] login failed ip=%s failures=%s", client_ip, count)
            raise AuthenticationError("Invalid username or password")

        await self._redis.delete(fail_key)

        ttl = self._settings.admin_session_ttl_seconds
        now = datetime.now(timezone.utc)
        session = AdminSessionDTO(
            username=self._settings.admin_username,
            created_at=now,
            expires_at=now + timedelta(seconds=ttl),
        )
        token = secrets.token_urlsafe(32)
        payload = {
            **session.model_dump(mode="json"),
            "credential_fp": _credential_fingerprint(self._settings),
        }
        stored = await self._redis.set(_session_key(token), payload, ttl=ttl)
        if not stored:
            raise ServiceUnavailableError("Login temporarily unavailable")

        logger.info("[admin_auth] login succeeded user=%s ip=%s", session.username, client_ip)
        return AdminLoginResultDTO(token=token, session=session)

    async def get_session(self, token: str) -> AdminSessionDTO | None:
        if not token or not self.is_configured:
            return None
        data = await self._redis.get(_session_key(token))
        if not isinstance(data, dict):
            return None
        # 아이디나 비밀번호가 교체되면 기존 세션은 무효
        if data.get("credential_fp") != _credential_fingerprint(self._settings):
            return None
        try:
            return AdminSessionDTO.model_validate(data)
        except ValueError:
            return None

    async def logout(self, token: str) -> None:
        if token:
            await self._redis.delete(_session_key(token))
