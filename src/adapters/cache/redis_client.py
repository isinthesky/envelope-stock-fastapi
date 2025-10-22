# -*- coding: utf-8 -*-
"""
Redis Cache Client - Redis 캐싱 클라이언트

시세 데이터, 계좌 정보, 토큰 등의 캐싱 관리
"""

import json
from typing import Any

import redis.asyncio as aioredis

from src.settings.config import settings


class RedisClient:
    """
    Redis 비동기 클라이언트

    캐시 저장/조회/삭제 기능 제공
    """

    def __init__(self) -> None:
        self.redis: aioredis.Redis | None = None

    # ==================== 연결 관리 ====================

    async def connect(self) -> None:
        """Redis 연결"""
        self.redis = await aioredis.from_url(
            settings.redis_url,
            password=settings.redis_password,
            max_connections=settings.redis_max_connections,
            decode_responses=True,  # 자동 UTF-8 디코딩
        )

    async def disconnect(self) -> None:
        """Redis 연결 종료"""
        if self.redis:
            await self.redis.close()
            self.redis = None

    async def ping(self) -> bool:
        """연결 상태 확인"""
        if self.redis:
            try:
                await self.redis.ping()
                return True
            except Exception:
                return False
        return False

    # ==================== 기본 CRUD ====================

    async def set(
        self, key: str, value: Any, ttl: int | None = None, serialize: bool = True
    ) -> bool:
        """
        캐시 저장

        Args:
            key: 키
            value: 값
            ttl: Time-To-Live (초), None이면 만료 없음
            serialize: JSON 직렬화 여부

        Returns:
            bool: 성공 여부
        """
        if not self.redis:
            return False

        try:
            if serialize:
                value = json.dumps(value, ensure_ascii=False)

            if ttl:
                await self.redis.setex(key, ttl, value)
            else:
                await self.redis.set(key, value)
            return True
        except Exception:
            return False

    async def get(self, key: str, deserialize: bool = True) -> Any | None:
        """
        캐시 조회

        Args:
            key: 키
            deserialize: JSON 역직렬화 여부

        Returns:
            Any | None: 캐시된 값 또는 None
        """
        if not self.redis:
            return None

        try:
            value = await self.redis.get(key)
            if value is None:
                return None

            if deserialize:
                return json.loads(value)
            return value
        except Exception:
            return None

    async def delete(self, key: str) -> bool:
        """
        캐시 삭제

        Args:
            key: 키

        Returns:
            bool: 성공 여부
        """
        if not self.redis:
            return False

        try:
            await self.redis.delete(key)
            return True
        except Exception:
            return False

    async def exists(self, key: str) -> bool:
        """
        캐시 존재 여부

        Args:
            key: 키

        Returns:
            bool: 존재 여부
        """
        if not self.redis:
            return False

        try:
            return await self.redis.exists(key) > 0
        except Exception:
            return False

    # ==================== TTL 관리 ====================

    async def expire(self, key: str, ttl: int) -> bool:
        """
        TTL 설정

        Args:
            key: 키
            ttl: Time-To-Live (초)

        Returns:
            bool: 성공 여부
        """
        if not self.redis:
            return False

        try:
            await self.redis.expire(key, ttl)
            return True
        except Exception:
            return False

    async def ttl(self, key: str) -> int:
        """
        남은 TTL 조회

        Args:
            key: 키

        Returns:
            int: 남은 TTL (초), -1: 만료 없음, -2: 키 없음
        """
        if not self.redis:
            return -2

        try:
            return await self.redis.ttl(key)
        except Exception:
            return -2

    # ==================== 패턴 검색 ====================

    async def keys(self, pattern: str) -> list[str]:
        """
        패턴으로 키 검색

        Args:
            pattern: 검색 패턴 (예: "market:*")

        Returns:
            list[str]: 매칭되는 키 리스트
        """
        if not self.redis:
            return []

        try:
            return await self.redis.keys(pattern)
        except Exception:
            return []

    async def delete_pattern(self, pattern: str) -> int:
        """
        패턴으로 키 일괄 삭제

        Args:
            pattern: 삭제 패턴

        Returns:
            int: 삭제된 키 수
        """
        if not self.redis:
            return 0

        try:
            keys = await self.keys(pattern)
            if keys:
                return await self.redis.delete(*keys)
            return 0
        except Exception:
            return 0

    # ==================== Hash 연산 ====================

    async def hset(self, name: str, key: str, value: Any, serialize: bool = True) -> bool:
        """
        Hash 필드 저장

        Args:
            name: Hash 이름
            key: 필드 키
            value: 값
            serialize: JSON 직렬화 여부

        Returns:
            bool: 성공 여부
        """
        if not self.redis:
            return False

        try:
            if serialize:
                value = json.dumps(value, ensure_ascii=False)
            await self.redis.hset(name, key, value)
            return True
        except Exception:
            return False

    async def hget(self, name: str, key: str, deserialize: bool = True) -> Any | None:
        """
        Hash 필드 조회

        Args:
            name: Hash 이름
            key: 필드 키
            deserialize: JSON 역직렬화 여부

        Returns:
            Any | None: 값 또는 None
        """
        if not self.redis:
            return None

        try:
            value = await self.redis.hget(name, key)
            if value is None:
                return None

            if deserialize:
                return json.loads(value)
            return value
        except Exception:
            return None

    async def hgetall(self, name: str, deserialize: bool = True) -> dict[str, Any]:
        """
        Hash 전체 조회

        Args:
            name: Hash 이름
            deserialize: JSON 역직렬화 여부

        Returns:
            dict[str, Any]: Hash 전체 데이터
        """
        if not self.redis:
            return {}

        try:
            data = await self.redis.hgetall(name)
            if deserialize:
                return {k: json.loads(v) for k, v in data.items()}
            return data
        except Exception:
            return {}

    # ==================== 도메인별 헬퍼 ====================

    async def cache_market_data(self, symbol: str, data: dict[str, Any]) -> bool:
        """
        시세 데이터 캐싱 (TTL: 5초)

        Args:
            symbol: 종목코드
            data: 시세 데이터

        Returns:
            bool: 성공 여부
        """
        key = f"market:{symbol}"
        return await self.set(key, data, ttl=settings.cache_ttl_market_data)

    async def get_market_data(self, symbol: str) -> dict[str, Any] | None:
        """
        시세 데이터 조회

        Args:
            symbol: 종목코드

        Returns:
            dict[str, Any] | None: 시세 데이터 또는 None
        """
        key = f"market:{symbol}"
        return await self.get(key)

    async def cache_account_data(self, account_no: str, data: dict[str, Any]) -> bool:
        """
        계좌 데이터 캐싱 (TTL: 30초)

        Args:
            account_no: 계좌번호
            data: 계좌 데이터

        Returns:
            bool: 성공 여부
        """
        key = f"account:{account_no}"
        return await self.set(key, data, ttl=settings.cache_ttl_account)

    async def get_account_data(self, account_no: str) -> dict[str, Any] | None:
        """
        계좌 데이터 조회

        Args:
            account_no: 계좌번호

        Returns:
            dict[str, Any] | None: 계좌 데이터 또는 None
        """
        key = f"account:{account_no}"
        return await self.get(key)


# ==================== 싱글톤 인스턴스 ====================

_redis_client_instance: RedisClient | None = None


async def get_redis_client() -> RedisClient:
    """
    RedisClient 싱글톤 인스턴스 반환

    Returns:
        RedisClient: Redis 클라이언트 인스턴스
    """
    global _redis_client_instance
    if _redis_client_instance is None:
        _redis_client_instance = RedisClient()
        await _redis_client_instance.connect()
    return _redis_client_instance
