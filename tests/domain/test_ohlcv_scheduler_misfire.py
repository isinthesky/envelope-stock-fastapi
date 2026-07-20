# -*- coding: utf-8 -*-
"""
OHLCV Cache Scheduler misfire/coalesce 정책 회귀 테스트

이벤트 루프 지연으로 초 단위 지각 시에도 cleanup/warmup/update 잡을
건너뛰지 않도록 job_defaults(coalesce=True, misfire_grace_time=300)를
적용한다. (조회성 잡이라 개별 override 없이 기본값 상속)
"""

from unittest.mock import patch

import pytest

from src.application.domain.ohlcv.scheduler import OHLCVCacheScheduler


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
async def test_ohlcv_scheduler_job_defaults_and_inheritance():
    scheduler = OHLCVCacheScheduler()

    # ohlcv/scheduler.py는 모듈 상단에서 import하므로 모듈 네임스페이스를 patch
    with patch(
        "src.application.domain.ohlcv.scheduler.AsyncIOScheduler", _DummyScheduler
    ):
        await scheduler.start()

    dummy = scheduler._scheduler
    assert isinstance(dummy, _DummyScheduler)
    assert dummy.job_defaults.get("coalesce") is True
    assert dummy.job_defaults.get("misfire_grace_time") == 300

    job_ids = {job.get("id") for job in dummy.jobs}
    assert {"ohlcv_cleanup", "ohlcv_warmup_until_yesterday", "ohlcv_update"} <= job_ids
    # 세 잡 모두 개별 override 없이 job_defaults를 상속해야 한다
    for job in dummy.jobs:
        assert "misfire_grace_time" not in job
        assert "coalesce" not in job
