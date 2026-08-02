# -*- coding: utf-8 -*-
"""
Buy Strategy Service - 스캔 동시성 테스트

스캔 동시성 제한이 결과 누락 없이 동작하는지 검증
"""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass

import pandas as pd
import pytest

from src.application.common.indicators import TechnicalIndicators
import src.application.domain.strategy.buy_strategy_service as buy_strategy_service_module
from src.application.domain.strategy.buy_strategy_service import BuyStrategyService
from src.application.domain.strategy.ohlcv_data_loader import LoadResult, LoadType


@dataclass
class DummyStock:
    symbol: str
    name: str
    market: str
    market_cap: float | None = None
    screening_score: float | None = None


class DummyUniverseRepo:
    def __init__(self, stocks: list[DummyStock]) -> None:
        self._stocks = stocks

    async def get_scan_stocks(
        self,
        market=None,
        include_etf: bool = True,
        session=None,
        limit: int = 1000,
    ) -> list[DummyStock]:
        return self._stocks[:limit]

    async def get_eligible_stocks(
        self,
        market=None,
        include_etf: bool = True,
        session=None,
        limit: int = 1000,
    ) -> list[DummyStock]:
        return self._stocks[:limit]


class DummyLoader:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self.active = 0
        self.max_active = 0

    async def load_ohlcv_with_stats(self, **kwargs) -> LoadResult:
        async with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)

        await asyncio.sleep(0.01)

        async with self._lock:
            self.active -= 1

        df = pd.DataFrame(
            {
                "close": [100.0, 101.0],
                "ma_short": [101.0, 101.0],
                "ma_long": [99.0, 99.0],
                "stoch_k": [20.0, 20.0],
                "stoch_d": [10.0, 10.0],
            }
        )
        return LoadResult(df=df, load_type=LoadType.CACHE_HIT, api_calls=0, new_candles=0)


class DummySession:
    def __init__(self) -> None:
        self._in_transaction = False

    def in_transaction(self) -> bool:
        return self._in_transaction

    async def commit(self) -> None:
        self._in_transaction = False

    async def rollback(self) -> None:
        self._in_transaction = False


@pytest.mark.asyncio
async def test_scan_golden_cross_concurrency_keeps_results(monkeypatch: pytest.MonkeyPatch) -> None:
    stocks = [
        DummyStock(symbol="000001", name="A", market="KOSPI"),
        DummyStock(symbol="000002", name="B", market="KOSPI"),
        DummyStock(symbol="000003", name="C", market="KOSPI"),
        DummyStock(symbol="000004", name="D", market="KOSPI"),
    ]
    repo = DummyUniverseRepo(stocks)
    service = BuyStrategyService(universe_repo=repo)
    loader = DummyLoader()

    @asynccontextmanager
    async def _dummy_session():
        yield DummySession()

    monkeypatch.setattr(buy_strategy_service_module, "AsyncSessionLocal", lambda: _dummy_session())
    monkeypatch.setattr(buy_strategy_service_module, "OHLCVDataLoader", lambda session=None: loader)
    monkeypatch.setattr(
        TechnicalIndicators,
        "prepare_golden_cross_indicators",
        staticmethod(lambda df, **kwargs: df),
    )

    result = await service.scan_golden_cross_candidates(
        market=None,
        gc_only=False,
        max_concurrent=2,
    )

    assert len(result.stocks) == len(stocks)
    assert [item.symbol for item in result.stocks] == sorted(stock.symbol for stock in stocks)
    assert {item.gc_state for item in result.stocks} == {"READY_TO_BUY"}
    assert result.errors == []
    assert loader.max_active <= 2


@pytest.mark.asyncio
async def test_scan_regime_filter_gates_gc_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    """[regime] gc_regime_filter_enabled 시: 하락레짐→GC 차단, 상승레짐→통과."""
    stocks = [DummyStock("000001", "A", "KOSPI"), DummyStock("000002", "B", "KOSPI")]
    service = BuyStrategyService(universe_repo=DummyUniverseRepo(stocks))
    loader = DummyLoader()

    @asynccontextmanager
    async def _ds():
        yield DummySession()

    monkeypatch.setattr(buy_strategy_service_module, "AsyncSessionLocal", lambda: _ds())
    monkeypatch.setattr(buy_strategy_service_module, "OHLCVDataLoader", lambda session=None: loader)
    monkeypatch.setattr(
        TechnicalIndicators,
        "prepare_golden_cross_indicators",
        staticmethod(lambda df, **kw: df),
    )

    async def _dummy_market(session, days=500):
        return ([100.0] * 250, [None] * 250, "KOSPI")

    async def _dummy_bench(session, symbol="069500", days=500):
        return None  # 레짐 판정은 _market_regime_ok 패치로 결정 → 벤치 로드는 무해한 스텁

    monkeypatch.setattr(buy_strategy_service_module, "get_kospi_or_proxy_closes", _dummy_market)
    monkeypatch.setattr(buy_strategy_service_module, "get_regime_benchmark_ohlc", _dummy_bench)
    monkeypatch.setattr(buy_strategy_service_module.settings, "gc_regime_filter_enabled", True)
    monkeypatch.setattr(buy_strategy_service_module.settings, "fear_buy_window_enabled", False)

    # 하락레짐 → GC 진입 차단(후보 0)
    monkeypatch.setattr(buy_strategy_service_module, "_market_regime_ok", lambda *a, **k: False)
    down = await service.scan_golden_cross_candidates(market=None, gc_only=False, max_concurrent=2)
    assert down.stocks == []

    # 상승레짐 → 통과(2 후보)
    monkeypatch.setattr(buy_strategy_service_module, "_market_regime_ok", lambda *a, **k: True)
    up = await service.scan_golden_cross_candidates(market=None, gc_only=False, max_concurrent=2)
    assert len(up.stocks) == 2
