# -*- coding: utf-8 -*-
"""Portfolio Parity Engine 테스트 (P2) — 집중도 캡/비용/공유 현금북."""

from decimal import Decimal

import numpy as np
import pandas as pd

from src.application.domain.backtest.dto import BacktestConfigDTO
from src.application.domain.backtest.portfolio_parity_engine import (
    PortfolioConstraints,
    PortfolioParityEngine,
)
from src.application.domain.strategy.dto import GoldenCrossConfigDTO, GoldenCrossMAConfig

CONFIG = GoldenCrossConfigDTO(ma_config=GoldenCrossMAConfig(short_period=5, long_period=60))
CAPITAL = BacktestConfigDTO(initial_capital=Decimal("10000000"))


def _crafted_df() -> pd.DataFrame:
    closes: list[float] = []
    p = 100.0
    for _ in range(90):
        p *= 1.004
        closes.append(p)
    for _ in range(3):
        p *= 0.965
        closes.append(p)
    for _ in range(30):
        p *= 1.006
        closes.append(p)
    for _ in range(40):
        p *= 1.004
        closes.append(p)
    for _ in range(30):
        p *= 0.97
        closes.append(p)
    n = len(closes)
    dates = pd.date_range("2023-01-02", periods=n, freq="B")
    close = np.array(closes, dtype=float)
    openp = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(openp, close) * 1.004
    low = np.minimum(openp, close) * 0.996
    return pd.DataFrame(
        {
            "timestamp": dates,
            "open": openp,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 100_000),
        }
    )


def _panels(symbols: list[str]) -> dict[str, pd.DataFrame]:
    df = _crafted_df()
    return {s: df.copy() for s in symbols}


def test_max_positions_cap_rejects_extra_entries():
    engine = PortfolioParityEngine(
        CONFIG, PortfolioConstraints(max_positions=1, allocation_ratio=0.1)
    )
    out = engine.run(_panels(["A", "B", "C"]), CAPITAL)

    # 3종목 동일 시그널(동일 날 매수) → 1개만 진입, 2개는 max_positions 거부
    assert out.entered_positions == 1
    assert out.max_concurrent_positions == 1
    assert sum(1 for r in out.rejected if r.reason == "max_positions") >= 2


def test_all_enter_when_capacity_allows():
    engine = PortfolioParityEngine(
        CONFIG, PortfolioConstraints(max_positions=3, allocation_ratio=0.1)
    )
    out = engine.run(_panels(["A", "B", "C"]), CAPITAL)

    assert out.entered_positions == 3
    assert out.max_concurrent_positions == 3
    assert not any(r.reason == "max_positions" for r in out.rejected)


def test_sector_cap_blocks_concentration():
    # 3종목 모두 SEMI 섹터, 섹터 비중 15% 상한 → 첫 종목만 진입
    sector_map = {"A": "SEMI", "B": "SEMI", "C": "SEMI"}
    engine = PortfolioParityEngine(
        CONFIG,
        PortfolioConstraints(
            max_positions=5,
            max_sector_weight=0.15,
            allocation_ratio=0.1,
            sector_map=sector_map,
        ),
    )
    out = engine.run(_panels(["A", "B", "C"]), CAPITAL)

    assert out.entered_positions == 1
    assert sum(1 for r in out.rejected if r.reason == "sector_cap") >= 2


def test_sector_cap_allows_diversified_entries():
    # 서로 다른 섹터면 동일 15% 상한에서도 각각 진입 가능
    sector_map = {"A": "SEMI", "B": "AUTO", "C": "BIO"}
    engine = PortfolioParityEngine(
        CONFIG,
        PortfolioConstraints(
            max_positions=5,
            max_sector_weight=0.15,
            allocation_ratio=0.1,
            sector_map=sector_map,
        ),
    )
    out = engine.run(_panels(["A", "B", "C"]), CAPITAL)

    assert out.entered_positions == 3
    assert not any(r.reason == "sector_cap" for r in out.rejected)


def test_costs_applied_and_portfolio_result_shape():
    engine = PortfolioParityEngine(CONFIG, PortfolioConstraints(max_positions=3))
    out = engine.run(_panels(["A", "B", "C"]), CAPITAL)

    r = out.result
    assert r.symbol == "PORTFOLIO"
    assert r.execution_timing == "same_close"
    assert r.total_trades >= 1  # crafted 경로는 익절 청산 발생
    # 비용/손익 반영으로 최종 자본이 초기와 달라짐
    assert r.final_capital != Decimal("10000000")
    assert len(r.daily_stats) == len(_crafted_df())


def _two_cycle_df() -> pd.DataFrame:
    """골든크로스 사이클을 2회 발생시키는 경로(매수→익절 ×2)."""

    def seg(p: float) -> tuple[list[float], float]:
        out: list[float] = []
        for _ in range(90):
            p *= 1.004
            out.append(p)
        for _ in range(3):
            p *= 0.965
            out.append(p)
        for _ in range(30):
            p *= 1.006
            out.append(p)
        for _ in range(40):
            p *= 1.004
            out.append(p)
        for _ in range(30):
            p *= 0.97
            out.append(p)
        return out, p

    p = 100.0
    s1, p = seg(p)
    s2, p = seg(p)
    closes = s1 + s2
    n = len(closes)
    dates = pd.date_range("2023-01-02", periods=n, freq="B")
    close = np.array(closes, dtype=float)
    openp = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(openp, close) * 1.004
    low = np.minimum(openp, close) * 0.996
    return pd.DataFrame(
        {
            "timestamp": dates,
            "open": openp,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 100_000),
        }
    )


def test_portfolio_single_symbol_matches_replay():
    """리팩터 파리티: 캡 비바인딩 단일종목 포트폴리오 == 검증된 단일종목 replay."""
    from src.application.domain.backtest.golden_cross_parity import GoldenCrossParityReplay

    df = _two_cycle_df()
    replay = GoldenCrossParityReplay(CONFIG)
    replay_res = replay.run("X", df.copy(), CAPITAL)

    engine = PortfolioParityEngine(CONFIG, PortfolioConstraints(max_positions=5))
    out = engine.run({"X": df.copy()}, CAPITAL)

    assert out.result.total_trades == replay_res.total_trades == 2
    assert [t.exit_reason for t in out.result.trades] == [t.exit_reason for t in replay_res.trades]


def test_rejected_buy_can_reenter_after_reset():
    """CRITICAL 수정: 캡으로 거부된 매수는 FSM이 reset되어 이후 재진입 가능(영구 락아웃 없음)."""
    two = _two_cycle_df()

    # 블로커 A: 1사이클만(B의 1차 매수 시점 슬롯 점유), 이후 평탄
    def seg(p: float):
        out = []
        for _ in range(90):
            p *= 1.004
            out.append(p)
        for _ in range(3):
            p *= 0.965
            out.append(p)
        for _ in range(30):
            p *= 1.006
            out.append(p)
        for _ in range(40):
            p *= 1.004
            out.append(p)
        for _ in range(30):
            p *= 0.97
            out.append(p)
        return out

    sa = seg(100.0)
    closesA = sa + [sa[-1]] * (len(two) - len(sa))
    n = len(closesA)
    dates = pd.date_range("2023-01-02", periods=n, freq="B")
    close = np.array(closesA, dtype=float)
    openp = np.concatenate([[close[0]], close[:-1]])
    dfA = pd.DataFrame(
        {
            "timestamp": dates,
            "open": openp,
            "high": np.maximum(openp, close) * 1.004,
            "low": np.minimum(openp, close) * 0.996,
            "close": close,
            "volume": np.full(n, 100_000),
        }
    )

    engine = PortfolioParityEngine(CONFIG, PortfolioConstraints(max_positions=1))
    out = engine.run({"A": dfA, "B": two.copy()}, CAPITAL)

    # A가 1차 슬롯 점유 → B 1차 매수 거부(reset) → B 2차 사이클에서 재진입
    assert out.entered_positions == 2
    assert sum(1 for r in out.rejected if r.reason == "max_positions") == 1
    assert out.result.total_trades == 2


def test_empty_panels_guard():
    engine = PortfolioParityEngine(CONFIG)
    try:
        engine.run({}, CAPITAL)
    except ValueError:
        return
    raise AssertionError("expected ValueError on empty panels")
