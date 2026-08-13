# -*- coding: utf-8 -*-
"""
Dependencies - 의존성 주입 중앙 관리

FastAPI Dependency Injection을 위한 공통 의존성 함수 정의
"""

import ipaddress
from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.cache.redis_client import RedisClient, get_redis_client
from src.adapters.database.connection import get_db
from src.adapters.database.repositories.order_repository import OrderRepository
from src.adapters.external.kis_api.auth import KISAuth, get_kis_auth
from src.adapters.external.kis_api.client import KISAPIClient, get_kis_client
from src.adapters.external.websocket.kis_websocket import KISWebSocket, get_kis_websocket
from src.application.common.exceptions import AuthorizationError

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

# ==================== Strategy Repositories (새 세션 계약) ====================
# NOTE: 새 패턴 - Repository는 생성자에서 session을 받지 않고,
#       메서드에서 session을 파라미터로 받습니다.


def get_strategy_repository() -> "StrategyRepository":
    """
    Strategy Repository Dependency (새 세션 계약)

    Returns:
        StrategyRepository: 전략 Repository (세션 없이 생성)
    """
    from src.adapters.database.repositories.strategy_repository import StrategyRepository

    return StrategyRepository()


def get_analysis_history_repository() -> "AnalysisHistoryRepository":
    """
    Analysis History Repository Dependency (새 세션 계약)

    Returns:
        AnalysisHistoryRepository: 분석 이력 Repository (세션 없이 생성)
    """
    from src.adapters.database.repositories.analysis_history_repository import (
        AnalysisHistoryRepository,
    )

    return AnalysisHistoryRepository()


def get_stock_universe_repository() -> "StockUniverseRepository":
    """
    Stock Universe Repository Dependency (새 세션 계약)

    Returns:
        StockUniverseRepository: 종목 유니버스 Repository (세션 없이 생성)
    """
    from src.adapters.database.repositories.stock_universe_repository import (
        StockUniverseRepository,
    )

    return StockUniverseRepository()


def get_strategy_symbol_state_repository() -> "StrategySymbolStateRepository":
    """
    Strategy Symbol State Repository Dependency (새 세션 계약)

    Returns:
        StrategySymbolStateRepository: 전략 종목 상태 Repository (세션 없이 생성)
    """
    from src.adapters.database.repositories.strategy_symbol_state_repository import (
        StrategySymbolStateRepository,
    )

    return StrategySymbolStateRepository()


# Type aliases for Strategy Repositories
StrategyRepositoryDep = Annotated["StrategyRepository", Depends(get_strategy_repository)]
AnalysisHistoryRepositoryDep = Annotated[
    "AnalysisHistoryRepository", Depends(get_analysis_history_repository)
]
StockUniverseRepositoryDep = Annotated[
    "StockUniverseRepository", Depends(get_stock_universe_repository)
]
StrategySymbolStateRepositoryDep = Annotated[
    "StrategySymbolStateRepository", Depends(get_strategy_symbol_state_repository)
]


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


# ==================== Domain Services ====================


async def get_market_data_service(
    kis_client: KISClientDep,
    redis_client: RedisDep,
) -> "MarketDataService":
    """
    MarketData Service Dependency

    Args:
        kis_client: KIS API Client
        redis_client: Redis Client

    Returns:
        MarketDataService: 시세 데이터 서비스
    """
    from src.application.domain.market_data.service import MarketDataService

    return MarketDataService(kis_client, redis_client)


# Type alias for Domain Services
MarketDataServiceDep = Annotated["MarketDataService", Depends(get_market_data_service)]


def get_strategy_service(
    strategy_repo: StrategyRepositoryDep,
    analysis_repo: AnalysisHistoryRepositoryDep,
) -> "StrategyService":
    """
    Strategy Service Dependency (새 세션 계약)

    Repository는 DI로 주입받고, session은 @transaction 데코레이터가 메서드에 주입합니다.

    Args:
        strategy_repo: Strategy Repository
        analysis_repo: Analysis History Repository

    Returns:
        StrategyService: 전략 서비스
    """
    from src.application.domain.strategy.strategy_service import StrategyService

    return StrategyService(
        strategy_repo=strategy_repo,
        analysis_repo=analysis_repo,
    )


# Type alias for Strategy Service
StrategyServiceDep = Annotated["StrategyService", Depends(get_strategy_service)]


def get_buy_strategy_service(
    universe_repo: StockUniverseRepositoryDep,
) -> "BuyStrategyService":
    """
    Buy Strategy Service Dependency (새 세션 계약)

    Repository는 DI로 주입받고, session은 @transaction 데코레이터가 메서드에 주입합니다.

    Args:
        universe_repo: Stock Universe Repository

    Returns:
        BuyStrategyService: 매수 전략 서비스
    """
    from src.application.domain.strategy.buy_strategy_service import BuyStrategyService

    return BuyStrategyService(universe_repo=universe_repo)


# Type alias for Buy Strategy Service
BuyStrategyServiceDep = Annotated["BuyStrategyService", Depends(get_buy_strategy_service)]


def get_public_strategy_service(
    strategy_service: StrategyServiceDep,
    market_data_service: MarketDataServiceDep,
    redis_client: RedisDep,
    universe_repo: StockUniverseRepositoryDep,
) -> "PublicStrategyService":
    """
    Public Strategy Service Dependency

    공개 전략 포털(/page/)의 시장 가용성 정책(설정 ∩ 실제 활성 유니버스)/
    rate limit/전역 락/고정 한도 스캔을 담당합니다.

    Args:
        strategy_service: Strategy Service
        redis_client: Redis Client
        universe_repo: Stock Universe Repository (가용 시장 count 조회용)

    Returns:
        PublicStrategyService: 공개 전략 서비스
    """
    from src.application.domain.strategy.public_strategy_service import PublicStrategyService

    return PublicStrategyService(
        strategy_service=strategy_service,
        market_data_service=market_data_service,
        redis_client=redis_client,
        universe_repo=universe_repo,
    )


# Type alias for Public Strategy Service
PublicStrategyServiceDep = Annotated["PublicStrategyService", Depends(get_public_strategy_service)]


# ==================== Admin Access Control ====================

UNSAFE_HTTP_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
ADMIN_CSRF_HEADER = "x-requested-with"
ADMIN_CSRF_HEADER_VALUE = "XMLHttpRequest"


def get_client_ip(request: Request, trusted_proxy_ips: list[str] | None = None) -> str:
    """클라이언트 IP 추출 (관리자 검증 + 공개 rate limit 공용)

    프록시 헤더(X-Forwarded-For/X-Real-IP)는 직접 연결 IP가
    신뢰할 수 있는 내부 네트워크(Docker bridge 등)인 경우에만 참조합니다.
    신뢰하지 않는 직접 접속의 위조 헤더는 무시됩니다.

    X-Forwarded-For는 프록시가 append하므로(nginx $proxy_add_x_forwarded_for),
    client가 왼쪽에 위조 값을 끼워넣을 수 있습니다. 따라서 왼쪽이 아니라
    오른쪽(가장 가까운 hop)부터 신뢰 프록시가 아닌 첫 IP(마지막 미신뢰 hop)를
    실제 클라이언트로 취급해, 위조를 통한 IP 스푸핑(관리자 허용 IP/공개 쿨다운
    우회)을 차단합니다.
    """
    direct_ip = request.client.host if request.client else None

    # 직접 연결 IP가 신뢰 가능한 프록시인 경우에만 헤더 참조
    if direct_ip:
        try:
            addr = ipaddress.ip_address(direct_ip)
            is_trusted = _is_ip_allowed(str(addr), trusted_proxy_ips or [])
        except ValueError:
            is_trusted = False

        if is_trusted:
            trusted = trusted_proxy_ips or []
            forwarded_for = request.headers.get("x-forwarded-for")
            if forwarded_for:
                hops = [p.strip() for p in forwarded_for.split(",") if p.strip()]
                # 오른쪽부터 신뢰 프록시가 아닌 첫 hop = 실제 클라이언트
                for candidate in reversed(hops):
                    if not _is_ip_allowed(candidate, trusted):
                        return candidate
                # 모든 hop이 신뢰 프록시(비정상)면 가장 바깥 값 사용
                if hops:
                    return hops[0]
            # X-Real-IP는 프록시가 overwrite로 설정하는 단일 값(single-proxy 전제)
            real_ip = request.headers.get("x-real-ip")
            if real_ip:
                return real_ip

        return direct_ip

    return "unknown"


def _is_ip_allowed(client_ip: str, allowed_ips: list[str]) -> bool:
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


async def verify_admin_access(request: Request) -> str:
    """
    관리자 API 접근 검증

    허용된 IP에서만 접근 가능합니다.

    Args:
        request: FastAPI Request 객체

    Returns:
        str: 클라이언트 IP

    Raises:
        AuthorizationError: 접근이 거부된 경우
    """
    from src.settings.config import get_settings

    settings = get_settings()
    client_ip = get_client_ip(request, settings.trusted_proxy_ips)

    if not _is_ip_allowed(client_ip, settings.admin_allowed_ips):
        raise AuthorizationError(
            message=f"Access denied from IP: {client_ip}",
        )

    if request.method.upper() in UNSAFE_HTTP_METHODS:
        requested_with = request.headers.get(ADMIN_CSRF_HEADER)
        if requested_with != ADMIN_CSRF_HEADER_VALUE:
            raise AuthorizationError(
                message="Admin write request missing CSRF guard header",
            )

    return client_ip


# Type alias for Admin Access
AdminAccessDep = Annotated[str, Depends(verify_admin_access)]
