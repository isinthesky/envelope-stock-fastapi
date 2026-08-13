# -*- coding: utf-8 -*-
"""
Public Strategy Service - 공개 전략 포털(/page/) 도메인 서비스

공개 스캔 보호 정책을 담당한다:
- DB 시장 가용성 사전조회(get_scan_capabilities) 실패 시에도 fail-closed 503
  (커넥션 풀 고갈/타임아웃 등으로 500이 새어나가지 않도록)
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

from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.cache.redis_client import RedisClient
from src.adapters.database.models.stock_universe import MarketType
from src.adapters.database.repositories.stock_universe_repository import (
    StockUniverseRepository,
)
from src.application.common.decorators import transaction
from src.application.common.exceptions import (
    ApplicationError,
    RateLimitExceededError,
    ResourceConflictError,
    ServiceUnavailableError,
    ValidationError,
)
from src.application.domain.strategy.public_dto import (
    PublicGoldenCrossScanDTO,
    PublicMarket,
    PublicRecommendationSnapshotDTO,
    PublicScanCapabilitiesDTO,
    PublicScanMarketOptionDTO,
    PublicUniverseMode,
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

# capability markets 표시 순서 (canonical) — KOSPI → KOSDAQ → ETF 고정
_MARKET_ORDER: tuple[MarketType, ...] = (MarketType.KOSPI, MarketType.KOSDAQ, MarketType.ETF)
_MARKET_LABELS: dict[MarketType, str] = {
    MarketType.KOSPI: "KOSPI",
    MarketType.KOSDAQ: "KOSDAQ",
    MarketType.ETF: "ETF",
}


class PublicStrategyService:
    """공개 전략 포털 유즈케이스 (가용성 정책 + rate limit + 고정 한도 스캔 + 스냅샷 조회)

    가용 시장 판정은 설정(ETF_UNIVERSE_ENABLED)과 실제 활성 유니버스(DB)의 교집합으로
    결정한다 — 설정만 보고 옵션을 만들면 refresh 실패/모드 전환 직후 스캔 불가능한
    시장이 노출될 수 있기 때문이다.
    """

    def __init__(
        self,
        strategy_service: StrategyService,
        redis_client: RedisClient,
        universe_repo: StockUniverseRepository,
    ) -> None:
        self._strategy_service = strategy_service
        self._redis = redis_client
        self._universe_repo = universe_repo

    # ==================== 공개 스캔 가용성 ====================

    async def get_scan_capabilities(self) -> PublicScanCapabilitiesDTO:
        """공개 스캔 가용 시장 조회 (DB count만 수행, 스캔/추천은 실행하지 않음)

        DB 커넥션 풀 고갈/타임아웃 등으로 사전조회 자체가 실패하면 Redis 미연결과
        동일하게 fail-closed 503으로 변환한다 — ApplicationError(예: 향후 명시적
        도메인 예외)는 그대로 전파하고, 그 외 인프라 예외만 503으로 감싼다. 이
        메서드는 GET /scan-capabilities와 run_public_scan() 양쪽에서 호출되므로
        한 곳에서 변환하면 두 경로 모두 커버된다.

        Raises:
            ServiceUnavailableError: DB 사전조회 실패(fail-closed)
        """
        try:
            # @transaction이 런타임에 session을 주입한다.
            return await self._fetch_scan_capabilities()  # type: ignore[call-arg]
        except ApplicationError:
            raise
        except Exception as e:
            logger.error(f"[PublicStrategyService] scan capabilities lookup failed: {e}")
            raise ServiceUnavailableError("Public scan is temporarily unavailable") from e

    @transaction
    async def _fetch_scan_capabilities(self, session: AsyncSession) -> PublicScanCapabilitiesDTO:
        """DB count 조회 (트랜잭션 경계 내부, 원본 예외는 변환 없이 전파)"""
        configured = self._configured_markets()
        counts = await self._universe_repo.get_scan_market_counts(configured, session=session)
        return self._build_scan_capabilities(counts)

    # ==================== 공개 스캔 ====================

    async def run_public_scan(
        self,
        market: str | None,
        client_ip: str,
    ) -> PublicGoldenCrossScanDTO:
        """공개 골든크로스 스캔 실행

        순서: wire market 형식 검증 → capability/활성 시장 조회 → effective market 결정
        → Redis 상태 확인 → IP 쿨다운 → 전역 락 → 제한형 스캔 → total_scanned=0 경쟁조건
        검사 → 공개 DTO projection → 소유 토큰 확인 후 락 해제.

        시장 가용성 검사(capability 조회~effective market 결정)는 Redis ping보다 먼저
        수행한다 — 지원하지 않는 시장을 선택한 사용자가 쿨다운을 소모하지 않게 한다.

        Args:
            market: 시장 필터 (KOSPI/KOSDAQ/ETF, None=전체)
            client_ip: 신뢰 프록시 규칙이 반영된 클라이언트 IP

        Raises:
            ValidationError: 허용되지 않은 wire market 값
            ResourceConflictError: 요청한 특정 시장이 비가용(details.reason=
                MARKET_NOT_AVAILABLE), 또는 사전 검사 뒤 실제 스캔 대상이 0으로
                바뀐 경쟁 조건(details.reason=SCAN_TARGETS_CHANGED)
            ServiceUnavailableError: 설정상 허용된 시장 전체가 비가용, DB 가용성
                사전조회 실패(fail-closed), 또는 Redis 미연결(fail-closed)
            RateLimitExceededError: IP 쿨다운 또는 전역 락 충돌 (429 + retry_after)
        """
        market = self._validate_market(market)

        capabilities = await self.get_scan_capabilities()
        effective_market, include_etf = self._resolve_effective_market(market, capabilities)

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
            # @transaction이 런타임에 session을 주입한다.
            result = await self._strategy_service.scan_golden_cross_candidates(  # type: ignore[call-arg]
                market=effective_market,
                stoch_threshold=PUBLIC_SCAN_STOCH_THRESHOLD,
                gc_only=PUBLIC_SCAN_GC_ONLY,
                include_etf=include_etf,
                limit=settings.public_strategy_scan_limit,
                max_concurrent=settings.public_strategy_scan_max_concurrent,
            )
            # 사전 capability 조회와 실제 스캔 사이 유니버스 refresh가 끼어들면
            # 대상이 0으로 바뀔 수 있다 — 정상 NO_MATCHES로 가장하지 않고 409로 변환
            if result.total_scanned == 0:
                raise ResourceConflictError(
                    message="Scan targets changed during availability check",
                    details={"reason": "SCAN_TARGETS_CHANGED"},
                )
            return PublicGoldenCrossScanDTO.from_internal(result, market=effective_market)
        finally:
            # 성공/실패와 무관하게 전역 락 해제 (프로세스 중단 시엔 TTL이 해제).
            # 비교+삭제를 Redis 안에서 원자적으로 실행해, 확인 직후 TTL이 만료되어
            # 다른 실행이 재획득한 락을 삭제하는 TOCTOU 경쟁 조건까지 방지한다.
            await self._redis.compare_and_delete(PUBLIC_SCAN_LOCK_KEY, lock_token)

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

    # ==================== 내부 헬퍼: 가용성 정책 ====================

    @staticmethod
    def _configured_markets() -> tuple[MarketType, ...]:
        """설정(ETF_UNIVERSE_ENABLED)에 따른 허용 시장 집합

        - True: ETF 전용 운영 정책 → ETF만 허용
        - False: 개별주 운영 → KOSPI/KOSDAQ만 허용

        ETF와 개별주를 동시에 허용하는 혼합 모드는 정의하지 않는다(범위 제외).
        """
        if settings.etf_universe_enabled:
            return (MarketType.ETF,)
        return (MarketType.KOSPI, MarketType.KOSDAQ)

    @staticmethod
    def _universe_mode() -> PublicUniverseMode:
        return "ETF_ONLY" if settings.etf_universe_enabled else "STOCKS"

    def _build_scan_capabilities(self, counts: dict[str, int]) -> PublicScanCapabilitiesDTO:
        """repository 집계 결과 → 공개 capability DTO (순수 변환, DB/Redis 접근 없음)

        markets는 설정과 실제 활성 유니버스의 교집합만 포함한다 — counts는 이미
        `_configured_markets()`로 조회된 값이므로, 여기서는 active_count>0인
        항목만 canonical 순서(KOSPI→KOSDAQ→ETF)로 필터링하면 그대로 교집합이 된다.
        """
        universe_mode = self._universe_mode()
        markets = [
            PublicScanMarketOptionDTO(
                value=market.value,
                label=_MARKET_LABELS[market],
                active_count=counts.get(market.value, 0),
            )
            for market in _MARKET_ORDER
            if counts.get(market.value, 0) > 0
        ]

        scan_enabled = len(markets) > 0
        allow_all = len(markets) >= 2

        default_market: PublicMarket | None
        if allow_all or not scan_enabled:
            default_market = None
        else:
            default_market = markets[0].value

        if not scan_enabled:
            notice = "현재 스캔 가능한 유니버스를 준비 중입니다."
        elif universe_mode == "ETF_ONLY":
            notice = "현재 ETF 전용 유니버스로 운영 중입니다."
        else:
            notice = None

        return PublicScanCapabilitiesDTO(
            scan_enabled=scan_enabled,
            universe_mode=universe_mode,
            allow_all=allow_all,
            default_market=default_market,
            markets=markets,
            notice=notice,
        )

    @staticmethod
    def _resolve_effective_market(
        requested: str | None,
        capabilities: PublicScanCapabilitiesDTO,
    ) -> tuple[PublicMarket | None, bool]:
        """null 정규화와 비가용 시장 거부

        Returns:
            (effective_market, include_etf) — effective_market은 실제 스캔에
            적용할 시장(None이면 개별주 복수 시장 통합 스캔), include_etf는
            scan_golden_cross_candidates에 전달할 ETF 포함 여부.

        Raises:
            ServiceUnavailableError: 설정상 허용된 시장 전체가 비가용
            ResourceConflictError: 명시적으로 요청한 시장이 비가용
                (details.reason=MARKET_NOT_AVAILABLE)
        """
        if not capabilities.scan_enabled:
            raise ServiceUnavailableError("Public scan universe is not ready")

        # canonical 순서(KOSPI→KOSDAQ→ETF)를 유지한 가용 시장 목록
        available_markets: list[PublicMarket] = [option.value for option in capabilities.markets]

        if requested is not None:
            if requested not in available_markets:
                raise ResourceConflictError(
                    message="Requested market is not available for public scan",
                    details={
                        "reason": "MARKET_NOT_AVAILABLE",
                        "requested_market": requested,
                        "available_markets": available_markets,
                        "universe_mode": capabilities.universe_mode,
                    },
                )
            # 위 in 검사(list[PublicMarket] 대상)로 mypy가 requested를 PublicMarket으로
            # 좁혀준다.
            return requested, PUBLIC_SCAN_INCLUDE_ETF

        if capabilities.allow_all:
            # 둘 이상의 개별주 시장이 가용 → market=None은 "전체(개별주만)"를 의미.
            # 이전에 남아있는 ETF 행이 있어도 설정 밖 ETF가 섞이지 않게 include_etf=False
            return None, False

        # 가용 시장이 정확히 하나 → 그 시장으로 정규화(ETF 모드의 기존 클라이언트 호환 포함)
        return available_markets[0], PUBLIC_SCAN_INCLUDE_ETF

    # ==================== 내부 헬퍼: wire 검증/키 ====================

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
