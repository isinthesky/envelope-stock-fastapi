# -*- coding: utf-8 -*-
"""
Dependencies - 의존성 주입 중앙 관리

FastAPI Dependency Injection을 위한 공통 의존성 함수 정의
"""

from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.cache.redis_client import RedisClient, get_redis_client
from src.adapters.database.connection import get_db
from src.adapters.database.repositories.order_repository import OrderRepository
from src.adapters.external.kis_api.auth import KISAuth, get_kis_auth
from src.adapters.external.kis_api.client import KISAPIClient, get_kis_client
from src.adapters.external.websocket.kis_websocket import KISWebSocket, get_kis_websocket

# ==================== Database Session ====================


async def get_session() -> AsyncIterator[AsyncSession]:
    """
    Database Session Dependency

    Yields:
        AsyncSession: 비동기 데이터베이스 세션
    """
    async for session in get_db():
        yield session


# Type alias for Database Session
DatabaseSession = Annotated[AsyncSession, Depends(get_session)]


# ==================== Repositories ====================


def get_order_repository(session: DatabaseSession) -> OrderRepository:
    """
    Order Repository Dependency

    Args:
        session: Database Session

    Returns:
        OrderRepository: 주문 Repository
    """
    return OrderRepository(session)


# Type aliases for Repositories
OrderRepositoryDep = Annotated[OrderRepository, Depends(get_order_repository)]

# TODO: 다른 Repository 추가
# AccountRepositoryDep = Annotated[AccountRepository, Depends(get_account_repository)]
# PositionRepositoryDep = Annotated[PositionRepository, Depends(get_position_repository)]
# StrategyRepositoryDep = Annotated[StrategyRepository, Depends(get_strategy_repository)]


# ==================== KIS API ====================


@lru_cache
def get_kis_auth_dependency() -> KISAuth:
    """
    KIS Auth Dependency (Singleton)

    Returns:
        KISAuth: KIS 인증 관리 인스턴스
    """
    return get_kis_auth()


@lru_cache
def get_kis_client_dependency() -> KISAPIClient:
    """
    KIS API Client Dependency (Singleton)

    Returns:
        KISAPIClient: KIS API 클라이언트 인스턴스
    """
    return get_kis_client()


@lru_cache
def get_kis_websocket_dependency() -> KISWebSocket:
    """
    KIS WebSocket Dependency (Singleton)

    Returns:
        KISWebSocket: KIS WebSocket 클라이언트 인스턴스
    """
    return get_kis_websocket()


# Type aliases for KIS API
KISAuthDep = Annotated[KISAuth, Depends(get_kis_auth_dependency)]
KISClientDep = Annotated[KISAPIClient, Depends(get_kis_client_dependency)]
KISWebSocketDep = Annotated[KISWebSocket, Depends(get_kis_websocket_dependency)]


# ==================== Redis Cache ====================


async def get_redis_dependency() -> RedisClient:
    """
    Redis Client Dependency

    Returns:
        RedisClient: Redis 클라이언트 인스턴스
    """
    return await get_redis_client()


# Type alias for Redis
RedisDep = Annotated[RedisClient, Depends(get_redis_dependency)]


# ==================== Settings ====================


@lru_cache
def get_settings_dependency():
    """
    Settings Dependency (Singleton)

    Returns:
        Settings: 애플리케이션 설정
    """
    from src.settings.config import get_settings

    return get_settings()


# Type alias for Settings
SettingsDep = Annotated[object, Depends(get_settings_dependency)]
