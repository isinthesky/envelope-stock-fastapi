# -*- coding: utf-8 -*-

from datetime import datetime, timezone

import pytest

from src.application.domain.market_data.service import MarketDataService


class DummyRedis:
    pass


class DummyKis:
    def __init__(self):
        self.last = None

    async def get(self, path, params=None, headers=None):
        self.last = {"path": path, "params": params or {}, "headers": headers or {}}
        # emulate chart response
        return {"output2": []}


@pytest.mark.asyncio
async def test_get_chart_data_formats_dates_in_kst():
    kis = DummyKis()
    svc = MarketDataService(kis, DummyRedis())

    # UTC datetime that becomes next day in KST (+9h)
    start_utc = datetime(2026, 2, 2, 16, 0, tzinfo=timezone.utc)  # KST 2026-02-03 01:00
    end_utc = datetime(2026, 2, 3, 0, 0, tzinfo=timezone.utc)     # KST 2026-02-03 09:00

    await svc.get_chart_data(
        symbol="005930",
        interval="1d",
        start_date=start_utc,
        end_date=end_utc,
        use_cache=False,
    )

    assert kis.last is not None
    p = kis.last["params"]
    assert p["FID_INPUT_DATE_1"] == "20260203"
    assert p["FID_INPUT_DATE_2"] == "20260203"


@pytest.mark.asyncio
async def test_get_chart_data_accepts_naive_start_with_aware_end():
    kis = DummyKis()
    svc = MarketDataService(kis, DummyRedis())

    await svc.get_chart_data(
        symbol="005930",
        interval="1d",
        start_date=datetime(2026, 2, 3),
        end_date=datetime(2026, 2, 4, tzinfo=timezone.utc),
        use_cache=False,
    )

    assert kis.last is not None
    assert kis.last["params"]["FID_INPUT_DATE_1"] == "20260203"
    assert kis.last["params"]["FID_INPUT_DATE_2"] == "20260204"
