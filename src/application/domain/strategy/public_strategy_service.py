# -*- coding: utf-8 -*-
"""
Public Strategy Service - 공개 전략 포털(/page/) 도메인 서비스

공개 스캔 보호 정책을 담당한다:
- Redis 미연결 시 fail-closed 503 (KIS 호출 보호가 무력화되지 않도록)
- IP(SHA-256 해시)별 쿨다운: SET NX EX
- 전역 단일 실행 락: SET NX EX + finally 해제 (프로세스 중단 시 TTL 자동 해제)
- 서버 고정 한도(stoch_threshold=30, gc_only, include_etf, limit, max_concurrent)로만
  StrategyService.scan_golden_cross_candidates 호출

공개 추천은 스케줄러가 생성한 스냅샷 캐시만 읽으며, 재계산을 유발하지 않는다.
"""

import hashlib
import logging
import uuid

from src.adapters.cache.redis_client import RedisClient
from src.application.common.exceptions import (
    RateLimitExceededError,
    ServiceUnavailableError,
    ValidationError,
)
from src.application.domain.strategy.public_dto import (
    PublicGoldenCrossScanDTO,
    PublicRecommendationSnapshotDTO,
)
from src.application.domain.strategy.strategy_service import StrategyService
from src.settings.config import settings

logger = logging.getLogger(__name__)

# Redis 키 (스냅샷 키는 notification_scheduler가 쓰고 여기서 읽는다)
PUBLIC_SCAN_COOLDOWN_KEY_PREFIX = "public:strategy:gc-scan:cooldown:"
PUBLIC_SCAN_LOCK_KEY = "public:strategy:gc-scan:lock"
PUBLIC_RECOMMENDATION_SNAPSHOT_KEY = "public:strategy:recommendations:latest"

# 공개 스캔 서버 고정 정책 (요청으로 조작 불가)
PUBLIC_SCAN_STOCH_THRESHOLD = 30.0
PUBLIC_SCAN_GC_ONLY = True
PUBLIC_SCAN_INCLUDE_ETF = True

_ALLOWED_MARKETS = {"KOSPI", "KOSDAQ", "ETF"}


class PublicStrategyService:
    """공개 전략 포털 유즈케이스 (rate limit + 고정 한도 스캔 + 스냅샷 조회)"""

    def __init__(
        self,
        strategy_service: StrategyService,
        redis_client: RedisClient,
    ) -> None:
        self._strategy_service = strategy_service
        self._redis = redis_client

    # ==================== 공개 스캔 ====================

    async def run_public_scan(
        self,
        market: str | None,
        client_ip: str,
    ) -> PublicGoldenCrossScanDTO:
        """공개 골든크로스 스캔 실행

        Args:
            market: 시장 필터 (KOSPI/KOSDAQ/ETF, None=전체)
            client_ip: 신뢰 프록시 규칙이 반영된 클라이언트 IP

        Raises:
            ValidationError: 허용되지 않은 market 값
            ServiceUnavailableError: Redis 미연결 (fail-closed)
            RateLimitExceededError: IP 쿨다운 또는 전역 락 충돌 (429 + retry_after)
        """
        market = self._validate_market(market)

        # Redis 장애 시 fail-open하면 KIS 호출 보호가 무력화되므로 fail-closed 503
        if not await self._redis.ping():
            raise ServiceUnavailableError("Public scan is temporarily unavailable")

        cooldown_seconds = settings.public_strategy_scan_cooldown_seconds
        lock_seconds = settings.public_strategy_scan_lock_seconds

        # 1) IP 쿨다운: 요청이 수락된 순간부터 유지 (실패 반복으로 외부 API를 압박하지 못하게
        #    전역 락 충돌로 스캔이 거절돼도 해제하지 않는다)
        #    ping 통과 직후 Redis가 끊기면 set_nx가 예외를 던지므로 fail-closed 503으로 변환한다
        #    (일반 set()처럼 오류를 False로 삼켜 429로 위장하지 않는다).
        cooldown_key = self._cooldown_key(client_ip)
        try:
            cooldown_acquired = await self._redis.set_nx(cooldown_key, "1", cooldown_seconds)
        except Exception as e:
            raise ServiceUnavailableError("Public scan is temporarily unavailable") from e
        if not cooldown_acquired:
            retry_after = await self._redis.ttl(cooldown_key)
            raise RateLimitExceededError(
                retry_after=retry_after if retry_after > 0 else cooldown_seconds
            )

        # 2) 전역 단일 실행 락 — 소유 토큰을 저장해, 스캔이 TTL을 넘겨 락이 만료된 뒤
        #    다른 실행이 잡은 락을 finally에서 지우지 않도록 한다
        lock_token = uuid.uuid4().hex
        try:
            lock_acquired = await self._redis.set_nx(PUBLIC_SCAN_LOCK_KEY, lock_token, lock_seconds)
        except Exception as e:
            raise ServiceUnavailableError("Public scan is temporarily unavailable") from e
        if not lock_acquired:
            retry_after = await self._redis.ttl(PUBLIC_SCAN_LOCK_KEY)
            raise RateLimitExceededError(
                retry_after=retry_after if retry_after > 0 else lock_seconds
            )

        try:
            result = await self._strategy_service.scan_golden_cross_candidates(
                market=market,
                stoch_threshold=PUBLIC_SCAN_STOCH_THRESHOLD,
                gc_only=PUBLIC_SCAN_GC_ONLY,
                include_etf=PUBLIC_SCAN_INCLUDE_ETF,
                limit=settings.public_strategy_scan_limit,
                max_concurrent=settings.public_strategy_scan_max_concurrent,
            )
            return PublicGoldenCrossScanDTO.from_internal(result)
        finally:
            # 성공/실패와 무관하게 전역 락 해제 (프로세스 중단 시엔 TTL이 해제).
            # 내 토큰일 때만 삭제 — TTL 만료 후 다른 실행이 재획득한 락 보호
            current = await self._redis.get(PUBLIC_SCAN_LOCK_KEY, deserialize=False)
            if current == lock_token:
                await self._redis.delete(PUBLIC_SCAN_LOCK_KEY)

    # ==================== 공개 추천 스냅샷 ====================

    async def get_public_recommendations(self) -> PublicRecommendationSnapshotDTO:
        """공개 추천 스냅샷 조회 (캐시 전용, 재계산 없음)

        캐시가 없거나(만료 포함) 읽기에 실패하면 available=false를 반환한다.
        """
        cached = await self._redis.get(PUBLIC_RECOMMENDATION_SNAPSHOT_KEY)
        if not cached:
            return PublicRecommendationSnapshotDTO.empty()

        try:
            snapshot = PublicRecommendationSnapshotDTO.model_validate(cached)
        except Exception as e:
            logger.warning(
                "[PublicStrategyService] Invalid recommendation snapshot cache, "
                f"returning empty: {e}"
            )
            return PublicRecommendationSnapshotDTO.empty()

        snapshot.available = True
        return snapshot

    # ==================== 내부 헬퍼 ====================

    @staticmethod
    def _validate_market(market: str | None) -> str | None:
        if market is None:
            return None
        if market not in _ALLOWED_MARKETS:
            raise ValidationError(
                message=f"Invalid market: {market}",
                details={"allowed": sorted(_ALLOWED_MARKETS)},
            )
        return market

    @staticmethod
    def _cooldown_key(client_ip: str) -> str:
        # 원본 IP를 Redis에 남기지 않도록 SHA-256 해시 사용
        ip_hash = hashlib.sha256(client_ip.encode("utf-8")).hexdigest()
        return f"{PUBLIC_SCAN_COOLDOWN_KEY_PREFIX}{ip_hash}"
