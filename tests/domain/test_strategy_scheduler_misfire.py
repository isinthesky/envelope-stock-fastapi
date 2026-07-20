# -*- coding: utf-8 -*-
"""
Strategy Scheduler misfire_grace_time 회귀 테스트

실주문(dry_run=False) 경로인 daily_strategy_execution 잡은 기본
misfire_grace_time=300(5분)을 쓰면 5분 지각 주문까지 실행될 수 있어
90초로 override한다. daily_universe_refresh는 조회성 잡이라 기본값
300초를 그대로 상속한다. (회귀 방지: override 유실 시 지각 실주문 위험)
"""

from unittest.mock import patch

import pytest

from src.application.domain.strategy.scheduler import StrategyScheduler


class _DummyScheduler:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.job_defaults = kwargs.get("job_defaults", {})
        self.jobs = []
        self.started = False

    def add_job(self, func, trigger, **kwargs):
        self.jobs.append({"func": func, "trigger": trigger, **kwargs})

    def start(self):
        self.started = True

    def shutdown(self, wait=False):
        self.started = False


@pytest.mark.asyncio
async def test_daily_strategy_execution_overrides_misfire_grace_time_to_90():
    scheduler = StrategyScheduler()

    with patch(
        "apscheduler.schedulers.asyncio.AsyncIOScheduler",
        side_effect=lambda *args, **kwargs: _DummyScheduler(*args, **kwargs),
    ):
        await scheduler.start()

    assert scheduler.is_running is True
    jobs = {job["id"]: job for job in scheduler.scheduler.jobs}

    # 실주문 잡: 지각 실주문 차단을 위해 90초로 명시 override
    assert jobs["daily_strategy_execution"]["misfire_grace_time"] == 90


@pytest.mark.asyncio
async def test_daily_universe_refresh_inherits_default_misfire_grace_time_300():
    scheduler = StrategyScheduler()

    with patch(
        "apscheduler.schedulers.asyncio.AsyncIOScheduler",
        side_effect=lambda *args, **kwargs: _DummyScheduler(*args, **kwargs),
    ):
        await scheduler.start()

    assert scheduler.is_running is True
    jobs = {job["id"]: job for job in scheduler.scheduler.jobs}

    # 조회성 잡: 개별 override 없이 job_defaults(300초) 상속
    assert "misfire_grace_time" not in jobs["daily_universe_refresh"]
    assert scheduler.scheduler.job_defaults["misfire_grace_time"] == 300
