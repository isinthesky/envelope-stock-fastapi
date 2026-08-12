# -*- coding: utf-8 -*-
"""PublicStrategyService 보호 정책 테스트

- 서버 고정 한도(stoch 30 / gc_only / include_etf / limit / max_concurrent)
- IP 쿨다운(SET NX EX)과 전역 락, fail-closed 503
- 추천 스냅샷은 캐시 전용(재계산 없음)
"""

from datetime import datetime
from decimal import Decimal

import pytest

from src.application.common.exceptions import (
    RateLimitExceededError,
    ServiceUnavailableError,
    ValidationError,
)
from src.application.domain.strategy.dto import (
    GoldenCrossRecommendationDTO,
    GoldenCrossScanItemDTO,
    GoldenCrossScanListDTO,
    IndustrySummaryDTO,
)
from src.application.domain.strategy.public_dto import (
    PublicGoldenCrossScanDTO,
    PublicRecommendationSnapshotDTO,
)
from src.application.domain.strategy.public_strategy_service import (
    PUBLIC_RECOMMENDATION_SNAPSHOT_KEY,
    PUBLIC_SCAN_LOCK_KEY,
    PublicStrategyService,
)
from src.settings.config import settings


class FakeRedis:
    """RedisClient 표면(set_nx/set/get/ttl/delete/ping)만 흉내내는 인메모리 fake"""

    def __init__(self, ping_ok: bool = True, set_nx_error: Exception | None = None):
        self.store: dict[str, object] = {}
        self.ttls: dict[str, int] = {}
        self.ping_ok = ping_ok
        self.set_nx_error = set_nx_error

    async def ping(self) -> bool:
        return self.ping_ok

    async def set_nx(self, key, value, ttl) -> bool:
        if self.set_nx_error is not None:
            raise self.set_nx_error
        if key in self.store:
            return False
        self.store[key] = value
        self.ttls[key] = ttl
        return True

    async def set(self, key, value, ttl=None, serialize=True, nx=False) -> bool:
        _ = serialize
        if nx and key in self.store:
            return False
        self.store[key] = value
        if ttl:
            self.ttls[key] = ttl
        return True

    async def get(self, key, deserialize=True):
        _ = deserialize
        return self.store.get(key)

    async def ttl(self, key) -> int:
        if key not in self.store:
            return -2
        return self.ttls.get(key, -1)

    async def delete(self, key) -> bool:
        self.store.pop(key, None)
        self.ttls.pop(key, None)
        return True


def _scan_item(**overrides) -> GoldenCrossScanItemDTO:
    base = dict(
        symbol="005930",
        name="삼성전자",
        market="KOSPI",
        current_price=Decimal("70000"),
        ma_short=Decimal("69000"),
        ma_long=Decimal("67000"),
        ma_gap_ratio=2.5,
        stoch_k=25.0,
        stoch_d=30.0,
        is_gc_active=True,
        gc_state="OPTIMAL_BUY",
        financial_filter_status="PASS",
        revenue_yoy=12.3,
        recommendation_score=88.0,
        recommendation_reasons=["내부 사유"],
        filter_reasons=["내부 필터 사유"],
    )
    base.update(overrides)
    return GoldenCrossScanItemDTO(**base)


def _scan_result() -> GoldenCrossScanListDTO:
    return GoldenCrossScanListDTO(
        stocks=[_scan_item()],
        total_scanned=100,
        gc_active_count=10,
        pullback_waiting_count=4,
        buy_interest_count=2,
        ready_to_buy_count=3,
        optimal_buy_count=1,
        scan_time=datetime(2026, 8, 13, 11, 30),
        errors=["종목 123456 내부 오류 상세"],
    )


class FakeStrategyService:
    def __init__(
        self, result: GoldenCrossScanListDTO | None = None, error: Exception | None = None
    ):
        self.calls: list[dict] = []
        self._result = result or _scan_result()
        self._error = error

    async def scan_golden_cross_candidates(self, **kwargs):
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        return self._result


def _service(
    redis=None, strategy=None
) -> tuple[PublicStrategyService, FakeRedis, FakeStrategyService]:
    redis = redis or FakeRedis()
    strategy = strategy or FakeStrategyService()
    return PublicStrategyService(strategy_service=strategy, redis_client=redis), redis, strategy


# ==================== 공개 스캔: 고정 정책 ====================


@pytest.mark.asyncio
async def test_scan_uses_fixed_server_policy() -> None:
    service, _redis, strategy = _service()

    result = await service.run_public_scan(market="KOSPI", client_ip="1.2.3.4")

    assert isinstance(result, PublicGoldenCrossScanDTO)
    assert strategy.calls == [
        {
            "market": "KOSPI",
            "stoch_threshold": 30.0,
            "gc_only": True,
            "include_etf": True,
            "limit": settings.public_strategy_scan_limit,
            "max_concurrent": settings.public_strategy_scan_max_concurrent,
        }
    ]


@pytest.mark.asyncio
async def test_scan_projection_excludes_internal_fields() -> None:
    service, _redis, _strategy = _service()

    result = await service.run_public_scan(market=None, client_ip="1.2.3.4")

    stock = result.stocks[0].model_dump()
    assert set(stock.keys()) == {
        "symbol",
        "name",
        "market",
        "current_price",
        "ma_gap_ratio",
        "stoch_k",
        "stoch_d",
        "gc_state",
    }
    dumped = result.model_dump()
    # 내부 오류 전문은 노출하지 않고 개수만 노출
    assert "errors" not in dumped
    assert dumped["error_count"] == 1
    # naive scan_time은 tz-aware(UTC)로 정규화되어야 브라우저가 로컬 시각으로 오해하지 않음
    assert result.scan_time.tzinfo is not None


@pytest.mark.asyncio
async def test_scan_rejects_invalid_market() -> None:
    service, _redis, strategy = _service()

    with pytest.raises(ValidationError):
        await service.run_public_scan(market="NASDAQ", client_ip="1.2.3.4")

    assert strategy.calls == []


# ==================== 공개 스캔: 쿨다운/전역 락 ====================


@pytest.mark.asyncio
async def test_second_request_from_same_ip_hits_cooldown() -> None:
    service, _redis, strategy = _service()

    await service.run_public_scan(market=None, client_ip="1.2.3.4")

    with pytest.raises(RateLimitExceededError) as exc_info:
        await service.run_public_scan(market=None, client_ip="1.2.3.4")

    assert exc_info.value.status_code == 429
    assert exc_info.value.details["retry_after"] > 0
    assert len(strategy.calls) == 1


@pytest.mark.asyncio
async def test_cooldown_key_stores_hash_not_raw_ip() -> None:
    service, redis, _strategy = _service()

    await service.run_public_scan(market=None, client_ip="9.9.9.9")

    cooldown_keys = [k for k in redis.store if k.startswith("public:strategy:gc-scan:cooldown:")]
    assert len(cooldown_keys) == 1
    assert "9.9.9.9" not in cooldown_keys[0]


@pytest.mark.asyncio
async def test_global_lock_blocks_other_ip_and_keeps_cooldown() -> None:
    service, redis, strategy = _service()
    # 다른 공개 스캔이 실행 중인 상태
    redis.store[PUBLIC_SCAN_LOCK_KEY] = "1"
    redis.ttls[PUBLIC_SCAN_LOCK_KEY] = 90

    with pytest.raises(RateLimitExceededError) as exc_info:
        await service.run_public_scan(market=None, client_ip="5.6.7.8")

    assert exc_info.value.details["retry_after"] == 90
    assert strategy.calls == []
    # 쿨다운은 요청이 수락된 순간부터 유지 (전역 락 충돌로 거절돼도 해제하지 않음)
    cooldown_keys = [k for k in redis.store if k.startswith("public:strategy:gc-scan:cooldown:")]
    assert len(cooldown_keys) == 1


@pytest.mark.asyncio
async def test_lock_released_after_success_but_cooldown_kept() -> None:
    service, redis, _strategy = _service()

    await service.run_public_scan(market=None, client_ip="1.2.3.4")

    assert PUBLIC_SCAN_LOCK_KEY not in redis.store
    cooldown_keys = [k for k in redis.store if k.startswith("public:strategy:gc-scan:cooldown:")]
    assert len(cooldown_keys) == 1


@pytest.mark.asyncio
async def test_finally_does_not_delete_lock_reacquired_by_another_run() -> None:
    """스캔이 락 TTL을 넘겨 만료된 뒤 다른 실행이 잡은 락은 finally가 지우지 않는다."""
    redis = FakeRedis()

    class SlowStrategyService(FakeStrategyService):
        async def scan_golden_cross_candidates(self, **kwargs):
            # 스캔 도중 락 TTL 만료 + 다른 실행이 재획득한 상황 시뮬레이션
            redis.store[PUBLIC_SCAN_LOCK_KEY] = "other-run-token"
            return await super().scan_golden_cross_candidates(**kwargs)

    strategy = SlowStrategyService()
    service, _, _ = _service(redis=redis, strategy=strategy)

    await service.run_public_scan(market=None, client_ip="1.2.3.4")

    # 다른 실행의 락은 그대로 유지된다
    assert redis.store.get(PUBLIC_SCAN_LOCK_KEY) == "other-run-token"


@pytest.mark.asyncio
async def test_lock_released_when_scan_fails() -> None:
    strategy = FakeStrategyService(error=RuntimeError("scan boom"))
    service, redis, _ = _service(strategy=strategy)

    with pytest.raises(RuntimeError):
        await service.run_public_scan(market=None, client_ip="1.2.3.4")

    assert PUBLIC_SCAN_LOCK_KEY not in redis.store


# ==================== 공개 스캔: fail-closed ====================


@pytest.mark.asyncio
async def test_redis_down_fails_closed_with_503() -> None:
    redis = FakeRedis(ping_ok=False)
    service, _, strategy = _service(redis=redis)

    with pytest.raises(ServiceUnavailableError) as exc_info:
        await service.run_public_scan(market=None, client_ip="1.2.3.4")

    assert exc_info.value.status_code == 503
    assert strategy.calls == []


@pytest.mark.asyncio
async def test_redis_error_after_ping_maps_to_503_not_429() -> None:
    # ping은 통과하지만 직후 set_nx가 인프라 오류를 던지는 경우 → 503 (429로 위장 금지)
    redis = FakeRedis(ping_ok=True, set_nx_error=ConnectionError("redis reset"))
    service, _, strategy = _service(redis=redis)

    with pytest.raises(ServiceUnavailableError) as exc_info:
        await service.run_public_scan(market=None, client_ip="1.2.3.4")

    assert exc_info.value.status_code == 503
    assert strategy.calls == []


# ==================== 추천 스냅샷 조회 ====================


def _recommendation() -> GoldenCrossRecommendationDTO:
    return GoldenCrossRecommendationDTO(
        top_stocks=[_scan_item()],
        top_industries=[IndustrySummaryDTO(industry_code="G45", industry_name="반도체", count=3)],
        buy_candidate_count=5,
        scan_time=datetime(2026, 8, 13, 11, 30),
        errors=["내부 경고 전문"],
        financial_status_counts={"PASS": 1},
        selection_criteria=["OPTIMAL_BUY 상태", "점수순 상위"],
    )


@pytest.mark.asyncio
async def test_recommendations_return_empty_when_cache_missing() -> None:
    service, _redis, strategy = _service()

    snapshot = await service.get_public_recommendations()

    assert snapshot.available is False
    assert snapshot.top_stocks == []
    assert strategy.calls == []  # 재계산을 유발하지 않음


@pytest.mark.asyncio
async def test_recommendations_read_cache_only() -> None:
    service, redis, strategy = _service()
    cached = PublicRecommendationSnapshotDTO.from_internal(
        _recommendation(), generated_at=datetime(2026, 8, 13, 11, 31)
    )
    redis.store[PUBLIC_RECOMMENDATION_SNAPSHOT_KEY] = cached.model_dump(mode="json")

    snapshot = await service.get_public_recommendations()

    assert snapshot.available is True
    assert snapshot.buy_candidate_count == 5
    assert [s.symbol for s in snapshot.top_stocks] == ["005930"]
    assert strategy.calls == []


@pytest.mark.asyncio
async def test_recommendations_invalid_cache_returns_empty() -> None:
    service, redis, _strategy = _service()
    redis.store[PUBLIC_RECOMMENDATION_SNAPSHOT_KEY] = {"top_stocks": "broken"}

    snapshot = await service.get_public_recommendations()

    assert snapshot.available is False


def test_public_snapshot_projection_excludes_internal_fields() -> None:
    snapshot = PublicRecommendationSnapshotDTO.from_internal(
        _recommendation(), generated_at=datetime(2026, 8, 13, 11, 31)
    )

    dumped = snapshot.model_dump()
    assert set(dumped.keys()) == {
        "available",
        "generated_at",
        "scan_time",
        "buy_candidate_count",
        "top_stocks",
        "top_industries",
        "selection_criteria",
    }
    # 내부 경고 전문/재무 필터 상세/추천 사유는 노출하지 않음
    stock = dumped["top_stocks"][0]
    assert set(stock.keys()) == {
        "symbol",
        "name",
        "market",
        "current_price",
        "gc_state",
        "recommendation_score",
    }
