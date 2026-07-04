# -*- coding: utf-8 -*-
from datetime import date

import pytest

import src.application.interface.api.backtest_router as backtest_router


@pytest.mark.asyncio
async def test_get_universe_golden_cross_forwards_backtest_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    async def fake_run_universe_golden_cross_backtest(
        request,
        session,
        service,
        admin_access,
    ):
        captured["request"] = request
        captured["session"] = session
        captured["service"] = service
        captured["admin_access"] = admin_access
        return request

    monkeypatch.setattr(
        backtest_router,
        "run_universe_golden_cross_backtest",
        fake_run_universe_golden_cross_backtest,
    )

    await backtest_router.get_universe_golden_cross_backtest(
        session="db-session",
        service="service",
        admin_access="127.0.0.1",
        market="KOSPI",
        eligible_only=True,
        limit=10,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 12, 31),
        portfolio=True,
        max_positions=7,
        execution_timing="same_close",
        cost_schedule_date=date(2024, 6, 1),
        commission_rate=0.0,
        tax_rate=0.0018,
        slippage_rate=0.0005,
    )

    request = captured["request"]
    assert request.backtest_config.execution_timing == "same_close"
    assert request.backtest_config.cost_schedule_date == date(2024, 6, 1)
    assert request.backtest_config.commission_rate == 0.0
    assert request.backtest_config.tax_rate == 0.0018
    assert request.backtest_config.slippage_rate == 0.0005
