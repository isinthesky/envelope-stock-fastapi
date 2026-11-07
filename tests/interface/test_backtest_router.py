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


@pytest.mark.asyncio
async def test_walk_forward_latest_returns_reader_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.application.domain.backtest.dto import WalkForwardReportDTO

    sentinel = WalkForwardReportDTO(available=True, verdict="NO_GO", symbols=98)

    class _FakeReader:
        def load_latest(self):
            return sentinel

    monkeypatch.setattr(backtest_router, "WalkForwardReportReader", lambda: _FakeReader())

    result = await backtest_router.get_latest_walk_forward_report(admin_access="127.0.0.1")

    assert result is sentinel
    assert result.available is True
    assert result.verdict == "NO_GO"


@pytest.mark.asyncio
async def test_walk_forward_latest_unavailable_when_no_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.application.domain.backtest.dto import WalkForwardReportDTO

    class _FakeReader:
        def load_latest(self):
            return WalkForwardReportDTO(available=False)

    monkeypatch.setattr(backtest_router, "WalkForwardReportReader", lambda: _FakeReader())

    result = await backtest_router.get_latest_walk_forward_report(admin_access=None)

    assert result.available is False
    assert result.verdict is None


@pytest.mark.asyncio
async def test_universe_selection_uses_fixed_symbols_without_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import datetime

    from src.application.domain.backtest.dto import UniverseBacktestRequestDTO

    def _no_scan(*_args, **_kwargs):
        raise AssertionError("fixed symbols must not trigger a universe scan")

    monkeypatch.setattr(backtest_router, "BuyStrategyService", _no_scan)
    request = UniverseBacktestRequestDTO(
        start_date=datetime(2024, 1, 1),
        end_date=datetime(2024, 12, 31),
        symbols=["069500", "005930", "069500"],
        limit=5,
    )
    symbols, method = await backtest_router._select_universe_symbols(
        request, None, {"stoch_oversold": 30.0}, 20, 60
    )
    assert symbols == ["069500", "005930"]
    assert method.startswith("fixed_symbols")


@pytest.mark.asyncio
async def test_universe_selection_ignores_today_signal_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """이전: 오늘의 gc_state(OPTIMAL_BUY 우선)로 걸러 종목을 선정 → look-ahead."""
    from datetime import datetime
    from types import SimpleNamespace

    from src.application.domain.backtest.dto import UniverseBacktestRequestDTO

    stocks = [
        SimpleNamespace(symbol="300000", gc_state="OPTIMAL_BUY", screening_score=1.0),
        SimpleNamespace(symbol="100000", gc_state="WAITING_FOR_GC", screening_score=1.0),
        SimpleNamespace(symbol="200000", gc_state="DEAD_CROSS", screening_score=1.0),
    ]

    class _FakeBuyService:
        def __init__(self, session):
            pass

        async def scan_golden_cross_candidates(self, **_kwargs):
            return SimpleNamespace(stocks=stocks)

    monkeypatch.setattr(backtest_router, "BuyStrategyService", _FakeBuyService)
    request = UniverseBacktestRequestDTO(
        start_date=datetime(2024, 1, 1), end_date=datetime(2024, 12, 31), limit=2
    )
    symbols, method = await backtest_router._select_universe_symbols(
        request, None, {"stoch_oversold": 30.0}, 20, 60
    )
    assert symbols == ["100000", "200000"]
    assert "no_signal_state_filter" in method
