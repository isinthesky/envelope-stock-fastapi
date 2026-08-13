# -*- coding: utf-8 -*-
"""PublicStrategyService 보호 정책 + 시장 가용성 정책 테스트

- 서버 고정 한도(stoch 30 / gc_only / include_etf / limit / max_concurrent)
- IP 쿨다운(SET NX EX)과 전역 락, fail-closed 503
- 추천 스냅샷은 캐시 전용(재계산 없음)
- 시장 가용성: 설정(ETF_UNIVERSE_ENABLED) ∩ 실제 활성 유니버스(count) 교집합 정책
  (`.omo/plans/public-scan-market-availability.md` 6.2)
"""

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

import src.application.common.decorators as decorators_module
from src.application.common.exceptions import (
    RateLimitExceededError,
    ResourceConflictError,
    ServiceUnavailableError,
    StrategyError,
    ValidationError,
)
from src.application.domain.strategy.dto import (
    GoldenCrossRecommendationDTO,
    GoldenCrossScanItemDTO,
    GoldenCrossScanListDTO,
    IndustrySummaryDTO,
)
from src.application.domain.strategy.public_dto import (
    PUBLIC_SCAN_MAX_RESULTS,
    PublicGoldenCrossScanDTO,
    PublicRecommendationSnapshotDTO,
    PublicSellAnalysisDTO,
)
from src.application.domain.strategy.public_strategy_service import (
    PUBLIC_RECOMMENDATION_SNAPSHOT_KEY,
    PUBLIC_SCAN_LOCK_KEY,
    PUBLIC_SELL_ANALYSIS_CACHE_KEY_PREFIX,
    PUBLIC_SELL_ANALYSIS_LOCK_KEY,
    PublicStrategyService,
)
from src.settings.config import settings


class FakeRedis:
    """RedisClient 표면(set_nx/compare_and_delete/get/ttl/ping)만 흉내내는 fake

    ping_calls/set_nx_calls는 "시장 가용성 검사가 Redis 보호자원보다 먼저 수행되어
    거부 시 Redis를 전혀 건드리지 않는다"를 검증하기 위한 호출 카운터다.
    """

    def __init__(self, ping_ok: bool = True, set_nx_error: Exception | None = None):
        self.store: dict[str, object] = {}
        self.ttls: dict[str, int] = {}
        self.ping_ok = ping_ok
        self.set_nx_error = set_nx_error
        self.ping_calls = 0
        self.set_nx_calls: list[tuple] = []
        self.compare_and_delete_calls: list[tuple[str, str]] = []

    async def ping(self) -> bool:
        self.ping_calls += 1
        return self.ping_ok

    async def set_nx(self, key, value, ttl) -> bool:
        self.set_nx_calls.append((key, value, ttl))
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

    async def compare_and_delete(self, key: str, expected_value: str) -> bool:
        self.compare_and_delete_calls.append((key, expected_value))
        if self.store.get(key) != expected_value:
            return False
        self.store.pop(key, None)
        self.ttls.pop(key, None)
        return True


class FakeUniverseRepo:
    """StockUniverseRepository 표면(get_scan_market_counts)만 흉내내는 fake

    실제 repository 계약과 동일하게, 요청한 시장 중 counts에 없는 시장은 0으로
    채워 반환한다. calls는 서비스가 어떤 시장 집합으로 집계를 요청했는지 기록한다.
    """

    def __init__(self, counts: dict[str, int] | None = None):
        self.counts = counts or {}
        self.calls: list[list[str]] = []

    async def get_scan_market_counts(self, markets, session=None) -> dict[str, int]:
        _ = session
        self.calls.append([m.value for m in markets])
        return {m.value: self.counts.get(m.value, 0) for m in markets}


class RaisingUniverseRepo:
    """get_scan_market_counts가 예외를 던지는 fake

    DB 커넥션 풀 고갈/타임아웃 등 인프라 장애를 시뮬레이션한다. Redis 호출과
    동일하게 fail-closed 503으로 변환되는지 검증하는 데 사용한다.
    """

    def __init__(self, error: Exception) -> None:
        self._error = error
        self.calls: list[list[str]] = []

    async def get_scan_market_counts(self, markets, session=None) -> dict[str, int]:
        _ = session
        self.calls.append([m.value for m in markets])
        raise self._error


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


def _scan_result(**overrides) -> GoldenCrossScanListDTO:
    base = dict(
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
    base.update(overrides)
    return GoldenCrossScanListDTO(**base)


class FakeStrategyService:
    def __init__(
        self, result: GoldenCrossScanListDTO | None = None, error: Exception | None = None
    ):
        self.calls: list[dict] = []
        self._result = result or _scan_result()
        self._error = error
        self.sell_result = _sell_internal_result()

    async def scan_golden_cross_candidates(self, **kwargs):
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        return self._result

    async def analyze_sell_signal(self, **kwargs):
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        return self.sell_result


def _sell_internal_result():
    """PublicSellAnalysisDTO projection에 필요한 내부 결과 표면."""
    return SimpleNamespace(
        symbol="005930",
        name="삼성전자",
        current_price=Decimal("70000"),
        analyzed_at=datetime(2026, 8, 13, 11, 30),
        candle_count=300,
        ma_short=Decimal("69000"),
        ma_long=Decimal("67000"),
        ma_gap_ratio=2.5,
        is_death_cross=False,
        is_gc_active=True,
        stoch_k=72.0,
        stoch_d=68.0,
        is_stoch_overbought=True,
        is_stoch_dead_cross=False,
        rsi=71.0,
        is_rsi_overbought=True,
        sell_phase="PHASE_2",
        sell_phase_name="매도 준비",
        sell_phase_action="비중 축소 준비",
        final_stage="REDUCE_1",
        final_ratio_min=0.2,
        final_ratio_max=0.3,
        sell_reasons=["과매수"] * 12,
        sell_stage_reasons=["모멘텀 둔화"],
        volume_ratio=1.4,
        is_volume_spike=True,
        price_drop_ratio=0.02,
        is_volume_sell_signal=True,
        adx=30.0,
        plus_di=20.0,
        minus_di=35.0,
        is_strong_uptrend=False,
        is_strong_downtrend=True,
        overbought_sell_blocked=False,
    )


def _service(
    redis=None,
    strategy=None,
    universe_repo=None,
) -> tuple[PublicStrategyService, FakeRedis, FakeStrategyService, FakeUniverseRepo]:
    redis = redis or FakeRedis()
    strategy = strategy or FakeStrategyService()
    # 기본: ETF 전용 모드 + ETF 221개 활성 (운영 실측과 동일한 baseline).
    # 시장 모드/가용성 자체를 검증하는 테스트는 universe_repo/etf_universe_enabled를
    # 명시적으로 override한다.
    universe_repo = universe_repo or FakeUniverseRepo({"ETF": 221})
    return (
        PublicStrategyService(
            strategy_service=strategy, redis_client=redis, universe_repo=universe_repo
        ),
        redis,
        strategy,
        universe_repo,
    )


class _DummySession:
    """@transaction이 여는 실 DB 세션을 대체하는 더미 (commit/rollback no-op)

    FakeUniverseRepo.get_scan_market_counts는 session을 사용하지 않으므로,
    get_scan_capabilities()가 실제 DB 연결 없이 동작하도록 세션 껍데기만 제공한다.
    """

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


class _DummySessionContext:
    async def __aenter__(self) -> _DummySession:
        return _DummySession()

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


@pytest.fixture(autouse=True)
def _stub_transaction_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_scan_capabilities()의 @transaction이 여는 AsyncSessionLocal()을 더미로 치환

    이 스위트는 실 DB를 사용하지 않는다 — FakeUniverseRepo가 session 인자를
    무시하므로 세션 자체는 커밋/롤백만 흉내내면 된다.
    """
    monkeypatch.setattr(decorators_module, "AsyncSessionLocal", lambda: _DummySessionContext())


@pytest.fixture(autouse=True)
def _default_etf_only_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """기본 실행 모드는 ETF 전용 — 시장 가용성과 무관한 쿨다운/락/fail-closed
    테스트가 새 가용성 게이트를 통과하도록 하는 안전한 기본값이다. 모드 자체를
    검증하는 테스트는 각자 override한다."""
    monkeypatch.setattr(settings, "etf_universe_enabled", True, raising=False)


# ==================== 공개 스캔: 가용성 — capability 조회 ====================


@pytest.mark.asyncio
async def test_etf_mode_capabilities_single_market_no_all_option() -> None:
    """ETF 모드 + ETF 221개: capability는 ETF 하나, allow_all=false, default=ETF"""
    service, _redis, _strategy, _universe = _service(universe_repo=FakeUniverseRepo({"ETF": 221}))

    capabilities = await service.get_scan_capabilities()

    assert capabilities.scan_enabled is True
    assert capabilities.universe_mode == "ETF_ONLY"
    assert capabilities.allow_all is False
    assert capabilities.default_market == "ETF"
    assert [(m.value, m.label, m.active_count) for m in capabilities.markets] == [
        ("ETF", "ETF", 221)
    ]
    assert capabilities.notice == "현재 ETF 전용 유니버스로 운영 중입니다."


@pytest.mark.asyncio
async def test_capabilities_scan_disabled_when_configured_market_has_zero_active() -> None:
    """ETF 모드 + 활성 ETF 0개: capability는 scan_enabled=false"""
    service, _redis, _strategy, _universe = _service(universe_repo=FakeUniverseRepo({"ETF": 0}))

    capabilities = await service.get_scan_capabilities()

    assert capabilities.scan_enabled is False
    assert capabilities.markets == []
    assert capabilities.default_market is None
    assert capabilities.notice == "현재 스캔 가능한 유니버스를 준비 중입니다."


@pytest.mark.asyncio
async def test_stocks_mode_capabilities_two_active_markets_allow_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """개별주 모드 + KOSPI/KOSDAQ 활성: capability에 두 시장과 allow_all=true"""
    monkeypatch.setattr(settings, "etf_universe_enabled", False, raising=False)
    service, _redis, _strategy, _universe = _service(
        universe_repo=FakeUniverseRepo({"KOSPI": 50, "KOSDAQ": 40})
    )

    capabilities = await service.get_scan_capabilities()

    assert capabilities.universe_mode == "STOCKS"
    assert capabilities.allow_all is True
    assert capabilities.default_market is None
    assert [m.value for m in capabilities.markets] == ["KOSPI", "KOSDAQ"]
    assert capabilities.notice is None


@pytest.mark.asyncio
async def test_stocks_mode_capabilities_single_active_market(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """개별주 모드 + KOSPI만 활성: capability는 KOSPI 하나, default=KOSPI"""
    monkeypatch.setattr(settings, "etf_universe_enabled", False, raising=False)
    service, _redis, _strategy, _universe = _service(
        universe_repo=FakeUniverseRepo({"KOSPI": 50, "KOSDAQ": 0})
    )

    capabilities = await service.get_scan_capabilities()

    assert capabilities.allow_all is False
    assert capabilities.default_market == "KOSPI"
    assert [m.value for m in capabilities.markets] == ["KOSPI"]


# ==================== 공개 스캔: DB 사전조회 실패 — fail-closed ====================


@pytest.mark.asyncio
async def test_get_scan_capabilities_db_failure_fails_closed_503() -> None:
    """DB 사전조회(get_scan_market_counts) 실패는 Redis 미연결과 동일하게
    fail-closed 503으로 변환된다 (500이 새어나가지 않음)"""
    universe_repo = RaisingUniverseRepo(RuntimeError("connection pool exhausted"))
    service, _redis, _strategy, _universe = _service(universe_repo=universe_repo)

    with pytest.raises(ServiceUnavailableError) as exc_info:
        await service.get_scan_capabilities()

    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_run_public_scan_db_failure_fails_closed_without_touching_redis() -> None:
    """run_public_scan 중 DB 사전조회가 실패하면 Redis ping/쿨다운/락을 전혀
    소모하지 않고 503으로 종료된다 (Redis 보호자원 미사용은 비가용 시장 케이스와 동일)"""
    universe_repo = RaisingUniverseRepo(RuntimeError("connection pool exhausted"))
    service, redis, strategy, _universe = _service(universe_repo=universe_repo)

    with pytest.raises(ServiceUnavailableError) as exc_info:
        await service.run_public_scan(market=None, client_ip="1.2.3.4")

    assert exc_info.value.status_code == 503
    assert strategy.calls == []
    assert redis.ping_calls == 0
    assert redis.set_nx_calls == []


# ==================== 공개 스캔: 가용성 — run_public_scan 정규화/거부 ====================


@pytest.mark.asyncio
async def test_etf_mode_null_market_normalizes_to_etf() -> None:
    """ETF 모드: market=null은 ETF로 정규화되어 전략 서비스에 전달된다"""
    service, _redis, strategy, _universe = _service(universe_repo=FakeUniverseRepo({"ETF": 221}))

    result = await service.run_public_scan(market=None, client_ip="1.2.3.4")

    assert strategy.calls[0]["market"] == "ETF"
    assert strategy.calls[0]["include_etf"] is True
    assert result.market == "ETF"


@pytest.mark.asyncio
async def test_etf_mode_rejects_explicit_kospi_without_touching_protections() -> None:
    """ETF 모드 + 명시적 KOSPI 요청: 409 MARKET_NOT_AVAILABLE, 스캔/Redis 미호출"""
    service, redis, strategy, _universe = _service(universe_repo=FakeUniverseRepo({"ETF": 221}))

    with pytest.raises(ResourceConflictError) as exc_info:
        await service.run_public_scan(market="KOSPI", client_ip="1.2.3.4")

    assert exc_info.value.status_code == 409
    assert exc_info.value.details == {
        "reason": "MARKET_NOT_AVAILABLE",
        "requested_market": "KOSPI",
        "available_markets": ["ETF"],
        "universe_mode": "ETF_ONLY",
    }
    assert strategy.calls == []
    assert redis.ping_calls == 0
    assert redis.set_nx_calls == []


@pytest.mark.asyncio
async def test_etf_mode_rejects_explicit_kosdaq_without_touching_protections() -> None:
    """ETF 모드 + 명시적 KOSDAQ 요청도 동일하게 409 + Redis/스캔 미호출"""
    service, redis, strategy, _universe = _service(universe_repo=FakeUniverseRepo({"ETF": 221}))

    with pytest.raises(ResourceConflictError) as exc_info:
        await service.run_public_scan(market="KOSDAQ", client_ip="1.2.3.4")

    assert exc_info.value.details["reason"] == "MARKET_NOT_AVAILABLE"
    assert exc_info.value.details["requested_market"] == "KOSDAQ"
    assert strategy.calls == []
    assert redis.ping_calls == 0
    assert redis.set_nx_calls == []


@pytest.mark.asyncio
async def test_zero_active_markets_returns_503_without_touching_protections() -> None:
    """설정상 허용 시장 전체가 비가용: 503, 스캔/Redis 보호자원 미사용"""
    service, redis, strategy, _universe = _service(universe_repo=FakeUniverseRepo({"ETF": 0}))

    with pytest.raises(ServiceUnavailableError) as exc_info:
        await service.run_public_scan(market=None, client_ip="1.2.3.4")

    assert exc_info.value.status_code == 503
    assert strategy.calls == []
    assert redis.ping_calls == 0
    assert redis.set_nx_calls == []


@pytest.mark.asyncio
async def test_stocks_mode_null_market_scans_both_and_excludes_etf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """개별주 모드 + KOSPI/KOSDAQ 활성: market=null은 include_etf=false로 호출된다"""
    monkeypatch.setattr(settings, "etf_universe_enabled", False, raising=False)
    service, _redis, strategy, _universe = _service(
        universe_repo=FakeUniverseRepo({"KOSPI": 50, "KOSDAQ": 40})
    )

    result = await service.run_public_scan(market=None, client_ip="1.2.3.4")

    assert strategy.calls[0]["market"] is None
    assert strategy.calls[0]["include_etf"] is False
    assert result.market is None


@pytest.mark.asyncio
async def test_stocks_mode_null_market_normalizes_to_only_active_market(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """개별주 모드 + KOSPI만 활성: null 요청은 KOSPI로 정규화된다"""
    monkeypatch.setattr(settings, "etf_universe_enabled", False, raising=False)
    service, _redis, strategy, _universe = _service(
        universe_repo=FakeUniverseRepo({"KOSPI": 50, "KOSDAQ": 0})
    )

    result = await service.run_public_scan(market=None, client_ip="1.2.3.4")

    assert strategy.calls[0]["market"] == "KOSPI"
    assert result.market == "KOSPI"


# ==================== 공개 매도 분석: projection/cache/protection ====================


@pytest.mark.asyncio
async def test_public_sell_analysis_uses_fixed_technical_only_parameters() -> None:
    service, redis, strategy, _universe = _service()

    result = await service.run_public_sell_analysis("005930", "1.2.3.4")

    assert result.symbol == "005930"
    assert result.final_stage == "REDUCE_1"
    assert result.final_stage_name == "1차 비중축소"
    assert len(result.sell_reasons) == 10
    assert result.is_cached is False
    assert strategy.calls == [
        {
            "symbol": "005930",
            "stoch_overbought": 70.0,
            "rsi_overbought": 70.0,
            "entry_price": None,
            "highest_price": None,
            "trailing_stop_activated": False,
            "force_refresh": False,
            "use_scoring": True,
            "merge_strategy": "conservative",
            "sell_mode": "hybrid",
            "include_overlays": False,
        }
    ]
    cache_key = f"{PUBLIC_SELL_ANALYSIS_CACHE_KEY_PREFIX}005930"
    assert redis.store[cache_key]["is_cached"] is False
    assert redis.ttls[cache_key] == settings.public_sell_analysis_cache_ttl_seconds
    assert redis.compare_and_delete_calls[-1][0] == PUBLIC_SELL_ANALYSIS_LOCK_KEY


@pytest.mark.asyncio
async def test_public_sell_analysis_cache_hit_bypasses_cooldown_and_strategy() -> None:
    redis = FakeRedis()
    cached = PublicSellAnalysisDTO.from_internal(_sell_internal_result())
    redis.store[f"{PUBLIC_SELL_ANALYSIS_CACHE_KEY_PREFIX}005930"] = cached.model_dump(mode="json")
    service, redis, strategy, _universe = _service(redis=redis)

    result = await service.run_public_sell_analysis("005930", "1.2.3.4")

    assert result.is_cached is True
    assert strategy.calls == []
    assert redis.set_nx_calls == []


@pytest.mark.asyncio
async def test_public_sell_analysis_invalid_cache_is_discarded_and_recomputed() -> None:
    redis = FakeRedis()
    cache_key = f"{PUBLIC_SELL_ANALYSIS_CACHE_KEY_PREFIX}005930"
    redis.store[cache_key] = {"unexpected": "payload"}
    service, redis, strategy, _universe = _service(redis=redis)

    result = await service.run_public_sell_analysis("005930", "1.2.3.4")

    assert result.is_cached is False
    assert len(strategy.calls) == 1
    assert redis.store[cache_key]["symbol"] == "005930"


@pytest.mark.asyncio
async def test_public_sell_analysis_data_error_maps_to_safe_409_and_releases_lock() -> None:
    strategy = FakeStrategyService(error=StrategyError("provider details must not leak"))
    service, redis, _strategy, _universe = _service(strategy=strategy)

    with pytest.raises(ResourceConflictError) as exc_info:
        await service.run_public_sell_analysis("005930", "1.2.3.4")

    assert exc_info.value.status_code == 409
    assert exc_info.value.details == {
        "reason": "ANALYSIS_DATA_UNAVAILABLE",
        "symbol": "005930",
    }
    assert "provider details" not in exc_info.value.message
    assert redis.compare_and_delete_calls[-1][0] == PUBLIC_SELL_ANALYSIS_LOCK_KEY


@pytest.mark.asyncio
async def test_public_sell_analysis_unexpected_error_maps_to_safe_503() -> None:
    strategy = FakeStrategyService(error=RuntimeError("upstream secret response"))
    service, _redis, _strategy, _universe = _service(strategy=strategy)

    with pytest.raises(ServiceUnavailableError) as exc_info:
        await service.run_public_sell_analysis("005930", "1.2.3.4")

    assert exc_info.value.status_code == 503
    assert "upstream secret response" not in exc_info.value.message


@pytest.mark.asyncio
async def test_public_sell_analysis_redis_down_fails_closed() -> None:
    service, redis, strategy, _universe = _service(redis=FakeRedis(ping_ok=False))

    with pytest.raises(ServiceUnavailableError):
        await service.run_public_sell_analysis("005930", "1.2.3.4")

    assert strategy.calls == []
    assert redis.set_nx_calls == []


@pytest.mark.asyncio
async def test_public_sell_analysis_global_lock_conflict_consumes_cooldown() -> None:
    redis = FakeRedis()
    redis.store[PUBLIC_SELL_ANALYSIS_LOCK_KEY] = "other-owner"
    redis.ttls[PUBLIC_SELL_ANALYSIS_LOCK_KEY] = 77
    service, redis, strategy, _universe = _service(redis=redis)

    with pytest.raises(RateLimitExceededError) as exc_info:
        await service.run_public_sell_analysis("005930", "1.2.3.4")

    assert exc_info.value.details["retry_after"] == 77
    assert len(redis.set_nx_calls) == 2
    assert strategy.calls == []


# ==================== 공개 스캔: total_scanned=0 경쟁 조건 / outcome ====================


@pytest.mark.asyncio
async def test_race_condition_total_scanned_zero_converts_to_conflict() -> None:
    """사전 count는 양수였지만 실제 스캔이 total_scanned=0이면 409 SCAN_TARGETS_CHANGED로 변환"""
    empty_result = _scan_result(stocks=[], total_scanned=0, gc_active_count=0, errors=[])
    strategy = FakeStrategyService(result=empty_result)
    service, redis, strategy, universe_repo = _service(strategy=strategy)

    with pytest.raises(ResourceConflictError) as exc_info:
        await service.run_public_scan(market=None, client_ip="1.2.3.4")

    assert exc_info.value.status_code == 409
    assert exc_info.value.details == {"reason": "SCAN_TARGETS_CHANGED"}
    # 사전 count는 양수였으므로 실제 스캔은 수행됐다 (경쟁 조건 시뮬레이션)
    assert len(strategy.calls) == 1
    assert universe_repo.calls == [["ETF"]]
    # 409로 변환돼도 전역 락은 finally에서 정상 해제된다
    assert PUBLIC_SCAN_LOCK_KEY not in redis.store


@pytest.mark.asyncio
async def test_no_matches_outcome_when_targets_scanned_but_no_candidates() -> None:
    """total_scanned>0, stocks=[]는 정상 결과이며 outcome=NO_MATCHES다 (200)"""
    result = _scan_result(stocks=[], total_scanned=50, gc_active_count=0, errors=[])
    strategy = FakeStrategyService(result=result)
    service, _redis, _strategy, _universe = _service(strategy=strategy)

    dto = await service.run_public_scan(market=None, client_ip="1.2.3.4")

    assert dto.outcome == "NO_MATCHES"
    assert dto.total_scanned == 50
    assert dto.stocks == []
    assert dto.market == "ETF"


@pytest.mark.asyncio
async def test_matches_found_outcome_when_stocks_present() -> None:
    service, _redis, _strategy, _universe = _service()

    dto = await service.run_public_scan(market=None, client_ip="1.2.3.4")

    assert dto.outcome == "MATCHES_FOUND"
    assert len(dto.stocks) == 1


# ==================== 공개 스캔: 고정 정책 ====================


@pytest.mark.asyncio
async def test_scan_uses_fixed_server_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    """개별주(STOCKS) 모드 + KOSPI 활성 상태에서 명시적 시장 요청은 고정 서버 정책으로 스캔한다

    (KOSPI가 무조건 스캔 성공한다는 가정은 개별주 모드 fixture로 명시 이동)
    """
    monkeypatch.setattr(settings, "etf_universe_enabled", False, raising=False)
    service, _redis, strategy, _universe = _service(
        universe_repo=FakeUniverseRepo({"KOSPI": 50, "KOSDAQ": 40})
    )

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
    service, _redis, _strategy, _universe = _service()

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
async def test_scan_projection_keeps_only_top_20_in_existing_priority_order() -> None:
    stocks = [
        _scan_item(symbol=f"{index:06d}", name=f"우선순위 {index}")
        for index in range(PUBLIC_SCAN_MAX_RESULTS + 5)
    ]
    strategy = FakeStrategyService(result=_scan_result(stocks=stocks))
    service, _redis, _strategy, _universe = _service(strategy=strategy)

    result = await service.run_public_scan(market=None, client_ip="1.2.3.4")

    assert len(result.stocks) == PUBLIC_SCAN_MAX_RESULTS
    assert [stock.symbol for stock in result.stocks] == [
        f"{index:06d}" for index in range(PUBLIC_SCAN_MAX_RESULTS)
    ]


@pytest.mark.asyncio
async def test_scan_rejects_invalid_market() -> None:
    service, _redis, strategy, _universe = _service()

    with pytest.raises(ValidationError):
        await service.run_public_scan(market="NASDAQ", client_ip="1.2.3.4")

    assert strategy.calls == []


# ==================== 공개 스캔: 쿨다운/전역 락 ====================


@pytest.mark.asyncio
async def test_second_request_from_same_ip_hits_cooldown() -> None:
    service, _redis, strategy, _universe = _service()

    await service.run_public_scan(market=None, client_ip="1.2.3.4")

    with pytest.raises(RateLimitExceededError) as exc_info:
        await service.run_public_scan(market=None, client_ip="1.2.3.4")

    assert exc_info.value.status_code == 429
    assert exc_info.value.details["retry_after"] > 0
    assert len(strategy.calls) == 1


@pytest.mark.asyncio
async def test_cooldown_key_stores_hash_not_raw_ip() -> None:
    service, redis, _strategy, _universe = _service()

    await service.run_public_scan(market=None, client_ip="9.9.9.9")

    cooldown_keys = [k for k in redis.store if k.startswith("public:strategy:gc-scan:cooldown:")]
    assert len(cooldown_keys) == 1
    assert "9.9.9.9" not in cooldown_keys[0]


@pytest.mark.asyncio
async def test_global_lock_blocks_other_ip_and_keeps_cooldown() -> None:
    service, redis, strategy, _universe = _service()
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
    service, redis, _strategy, _universe = _service()

    await service.run_public_scan(market=None, client_ip="1.2.3.4")

    assert PUBLIC_SCAN_LOCK_KEY not in redis.store
    assert redis.compare_and_delete_calls[0][0] == PUBLIC_SCAN_LOCK_KEY
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
    service, _, _, _ = _service(redis=redis, strategy=strategy)

    await service.run_public_scan(market=None, client_ip="1.2.3.4")

    # 다른 실행의 락은 그대로 유지된다
    assert redis.store.get(PUBLIC_SCAN_LOCK_KEY) == "other-run-token"


@pytest.mark.asyncio
async def test_lock_released_when_scan_fails() -> None:
    strategy = FakeStrategyService(error=RuntimeError("scan boom"))
    service, redis, _, _ = _service(strategy=strategy)

    with pytest.raises(RuntimeError):
        await service.run_public_scan(market=None, client_ip="1.2.3.4")

    assert PUBLIC_SCAN_LOCK_KEY not in redis.store


# ==================== 공개 스캔: fail-closed ====================


@pytest.mark.asyncio
async def test_redis_down_fails_closed_with_503() -> None:
    redis = FakeRedis(ping_ok=False)
    service, _, strategy, _universe = _service(redis=redis)

    with pytest.raises(ServiceUnavailableError) as exc_info:
        await service.run_public_scan(market=None, client_ip="1.2.3.4")

    assert exc_info.value.status_code == 503
    assert strategy.calls == []


@pytest.mark.asyncio
async def test_redis_error_after_ping_maps_to_503_not_429() -> None:
    # ping은 통과하지만 직후 set_nx가 인프라 오류를 던지는 경우 → 503 (429로 위장 금지)
    redis = FakeRedis(ping_ok=True, set_nx_error=ConnectionError("redis reset"))
    service, _, strategy, _universe = _service(redis=redis)

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
    service, _redis, strategy, _universe = _service()

    snapshot = await service.get_public_recommendations()

    assert snapshot.available is False
    assert snapshot.top_stocks == []
    assert strategy.calls == []  # 재계산을 유발하지 않음


@pytest.mark.asyncio
async def test_recommendations_read_cache_only() -> None:
    service, redis, strategy, _universe = _service()
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
    service, redis, _strategy, _universe = _service()
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
