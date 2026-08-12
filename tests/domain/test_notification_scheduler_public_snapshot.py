# -*- coding: utf-8 -*-
"""매수 알림 Job의 공개 추천 스냅샷 캐시 테스트

- 추천 계산 직후 공개 projection이 Redis에 저장된다
- Telegram 발송 실패/중복 스킵/캐시 저장 실패가 기존 결과 의미를 깨지 않는다
"""

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import src.application.domain.strategy.notification_scheduler as scheduler_module
from src.application.domain.strategy.dto import (
    GoldenCrossRecommendationDTO,
    GoldenCrossScanItemDTO,
    IndustrySummaryDTO,
)
from src.application.domain.strategy.notification_scheduler import NotificationScheduler
from src.application.domain.strategy.public_strategy_service import (
    PUBLIC_RECOMMENDATION_SNAPSHOT_KEY,
)
from src.settings.config import settings


class FakeRedis:
    def __init__(self, set_result: bool = True):
        self.set_calls: list[dict] = []
        self._set_result = set_result

    async def set(self, key, value, ttl=None, serialize=True, nx=False) -> bool:
        _ = serialize, nx
        self.set_calls.append({"key": key, "value": value, "ttl": ttl})
        return self._set_result


def _recommendation_dto() -> GoldenCrossRecommendationDTO:
    return GoldenCrossRecommendationDTO(
        top_stocks=[
            GoldenCrossScanItemDTO(
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
                recommendation_score=88.0,
                recommendation_reasons=["내부 추천 사유"],
            )
        ],
        top_industries=[IndustrySummaryDTO(industry_code="G45", industry_name="반도체", count=3)],
        buy_candidate_count=5,
        scan_time=datetime(2026, 8, 13, 11, 30),
        errors=["내부 경고 전문"],
        selection_criteria=["OPTIMAL_BUY 상태"],
    )


class DummyStrategyService:
    async def get_golden_cross_recommendations(self, **kwargs):
        _ = kwargs
        return _recommendation_dto()


def _wire(monkeypatch: pytest.MonkeyPatch, fake_redis, notifier_result: bool = True):
    notifier = SimpleNamespace(
        send_golden_cross_recommendations_summary=AsyncMock(return_value=notifier_result),
    )

    async def _fake_get_redis_client():
        if isinstance(fake_redis, Exception):
            raise fake_redis
        return fake_redis

    monkeypatch.setattr(scheduler_module, "StrategyService", DummyStrategyService)
    monkeypatch.setattr(scheduler_module, "get_telegram_notifier", lambda: notifier)
    monkeypatch.setattr(scheduler_module, "get_redis_client", _fake_get_redis_client)
    return notifier


@pytest.mark.asyncio
async def test_buy_notification_caches_public_snapshot(monkeypatch: pytest.MonkeyPatch):
    scheduler = NotificationScheduler()
    fake_redis = FakeRedis()
    notifier = _wire(monkeypatch, fake_redis)

    result = await scheduler.execute_buy_notification_now(slot_label="manual")

    assert result["success"] is True
    assert result["sent"] is True
    notifier.send_golden_cross_recommendations_summary.assert_awaited_once()

    assert len(fake_redis.set_calls) == 1
    call = fake_redis.set_calls[0]
    assert call["key"] == PUBLIC_RECOMMENDATION_SNAPSHOT_KEY
    assert call["ttl"] == settings.public_strategy_recommendation_ttl_seconds

    snapshot = call["value"]
    assert snapshot["available"] is True
    assert snapshot["buy_candidate_count"] == 5
    # 공개 projection: 내부 경고 전문/재무 필터 상세는 저장되지 않음
    assert "errors" not in snapshot
    assert set(snapshot["top_stocks"][0].keys()) == {
        "symbol",
        "name",
        "market",
        "current_price",
        "gc_state",
        "recommendation_score",
    }


@pytest.mark.asyncio
async def test_duplicate_skip_still_caches_snapshot(monkeypatch: pytest.MonkeyPatch):
    scheduler = NotificationScheduler()
    fake_redis = FakeRedis()
    notifier = _wire(monkeypatch, fake_redis)
    monkeypatch.setattr(
        scheduler._dedupe, "is_duplicate_notification", lambda *args, **kwargs: True
    )

    result = await scheduler.execute_buy_notification_now(slot_label="manual")

    assert result["duplicate_skipped"] is True
    notifier.send_golden_cross_recommendations_summary.assert_not_awaited()
    # 중복 스킵이어도 계산된 추천은 캐시된다
    assert len(fake_redis.set_calls) == 1


@pytest.mark.asyncio
async def test_telegram_failure_still_caches_snapshot(monkeypatch: pytest.MonkeyPatch):
    scheduler = NotificationScheduler()
    fake_redis = FakeRedis()
    _wire(monkeypatch, fake_redis, notifier_result=False)

    result = await scheduler.execute_buy_notification_now(slot_label="manual")

    assert result["sent"] is False
    assert len(fake_redis.set_calls) == 1
    assert fake_redis.set_calls[0]["value"]["available"] is True


@pytest.mark.asyncio
async def test_snapshot_save_failure_does_not_break_notification(
    monkeypatch: pytest.MonkeyPatch,
):
    scheduler = NotificationScheduler()
    fake_redis = FakeRedis(set_result=False)
    _wire(monkeypatch, fake_redis)

    result = await scheduler.execute_buy_notification_now(slot_label="manual")

    assert result["success"] is True
    assert result["sent"] is True
    assert scheduler.get_status()["last_job_results"][0]["job_type"] == "buy_notification"


@pytest.mark.asyncio
async def test_snapshot_redis_error_does_not_break_notification(
    monkeypatch: pytest.MonkeyPatch,
):
    scheduler = NotificationScheduler()
    _wire(monkeypatch, RuntimeError("redis unavailable"))

    result = await scheduler.execute_buy_notification_now(slot_label="manual")

    assert result["success"] is True
    assert result["sent"] is True
