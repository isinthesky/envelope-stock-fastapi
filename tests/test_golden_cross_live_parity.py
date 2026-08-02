# -*- coding: utf-8 -*-
"""
Golden Cross Live-Parity 골든 회귀 테스트 (P0 시그널 단일화)

핵심 불변식:
    백테스트(`GoldenCrossParityReplay`)가 생성하는 진입/청산 시그널은
    실주문 경로(`golden_cross_engine._process_symbol` + `GoldenCrossStateMachine`)와
    **바 단위로 동일**해야 한다.

    이를 위해 이 테스트는 실주문 오케스트레이션을 독립적으로 재구현한
    `reference_live_schedule`(DB-row 스타일 상태 보관)과 parity 엔진의 스케줄이
    여러 합성 시계열에서 정확히 일치함을 고정한다. 향후 누군가 백테스트 매수
    로직을 라이브와 다르게 바꾸면 이 테스트가 깨진다.
"""

from decimal import Decimal

import numpy as np
import pandas as pd

from src.adapters.database.models.strategy_symbol_state import SymbolState
from src.application.domain.backtest.dto import BacktestConfigDTO
from src.application.domain.backtest.golden_cross_parity import GoldenCrossParityReplay
from src.application.domain.strategy.dto import GoldenCrossConfigDTO, GoldenCrossMAConfig
from src.application.domain.strategy.state_machine import GoldenCrossStateMachine, Signal

# long_period ge=60 제약이 있어 60을 사용(짧은 합성 경로로 동일 코드 경로 구동).
CONFIG = GoldenCrossConfigDTO(ma_config=GoldenCrossMAConfig(short_period=5, long_period=60))

FSM_EXIT_REASONS = {"dead_cross", "stop_loss", "take_profit", "trailing_stop", "max_hold"}
BUY_REASONS = {"stoch_recovery_crossover", "stoch_strong_recovery"}


def _make_df(closes: list[float]) -> pd.DataFrame:
    n = len(closes)
    # 비용 스케줄 지원 구간(>=2023-01-01)에 맞춰 시작일을 둔다.
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


def _crafted_df() -> pd.DataFrame:
    """골든크로스→풀백→회복 매수→익절을 결정적으로 발생시키는 경로."""
    closes: list[float] = []
    p = 100.0
    for _ in range(90):  # 완만한 상승 → MA5>MA60(작은 갭) 확립
        p *= 1.004
        closes.append(p)
    for _ in range(3):  # 급락 → 스토캐스틱 과매도
        p *= 0.965
        closes.append(p)
    for _ in range(30):  # 회복 → OPTIMAL_BUY 매수
        p *= 1.006
        closes.append(p)
    for _ in range(40):  # 랠리 → 익절/청산
        p *= 1.004
        closes.append(p)
    for _ in range(30):  # 하락 → 데드크로스
        p *= 0.97
        closes.append(p)
    return _make_df(closes)


def _walk_df(seed: int, n: int = 220) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    steps = rng.normal(0.0015, 0.02, n)
    closes = 100.0 * np.exp(np.cumsum(steps))
    return _make_df(list(closes))


def reference_live_schedule(
    prepared: pd.DataFrame, config: GoldenCrossConfigDTO
) -> list[tuple[int, str, str | None]]:
    """실주문 `_process_symbol` 오케스트레이션의 독립 재구현(레퍼런스).

    parity 엔진과 다른 코드 스타일(DB-row 형태 dict 상태)로 작성하여
    parity 엔진이 라이브 동작을 올바르게 미러링하는지 교차 검증한다.
    """
    sm = GoldenCrossStateMachine(config)
    warmup = config.ma_config.long_period + 10
    n = len(prepared)
    out: list[tuple[int, str, str | None]] = []
    if n < warmup:
        return out

    snap = GoldenCrossParityReplay._snapshot
    rows = [snap(prepared.iloc[i]) for i in range(n)]
    st: dict | None = None

    for i in range(warmup - 1, n):
        cur, prev = rows[i], rows[i - 1]
        if st is None:
            st = {
                "state": sm.get_initial_state(cur).value,
                "gc_date": None,
                "pullback_date": None,
                "entry_price": None,
                "entry_date": None,
                "highest_price": None,
                "trailing": False,
            }
        tr = sm.process(
            current=cur,
            prev=prev,
            current_state=SymbolState(st["state"]),
            gc_date=st["gc_date"],
            pullback_date=st["pullback_date"],
            entry_price=st["entry_price"],
            entry_date=st["entry_date"],
            highest_price=st["highest_price"],
            trailing_stop_activated=st["trailing"],
        )
        if st["state"] == SymbolState.IN_POSITION.value:
            if st["highest_price"] is None or cur.close > st["highest_price"]:
                st["highest_price"] = cur.close
            if st["entry_price"] and st["entry_price"] > 0:
                pnl = float((cur.close - st["entry_price"]) / st["entry_price"])
                if pnl >= config.risk_config.trailing_stop_activation and not st["trailing"]:
                    st["trailing"] = True

        if tr.signal == Signal.BUY:
            out.append((i, "buy", tr.reason))
            st = {
                "state": tr.new_state.value,
                "gc_date": None,
                "pullback_date": None,
                "entry_price": cur.close,
                "entry_date": cur.timestamp,
                "highest_price": None,
                "trailing": False,
            }
        elif tr.signal == Signal.SELL:
            out.append((i, "sell", tr.reason))
            st = {
                "state": SymbolState.WAITING_FOR_GC.value,
                "gc_date": None,
                "pullback_date": None,
                "entry_price": None,
                "entry_date": None,
                "highest_price": None,
                "trailing": False,
            }
        else:
            st["state"] = tr.new_state.value
            st["gc_date"] = tr.gc_date
            st["pullback_date"] = tr.pullback_date
    return out


# ==================== (A) 라이브 패리티: parity == reference ====================


def test_parity_schedule_matches_live_reference_on_crafted_path():
    replay = GoldenCrossParityReplay(CONFIG)
    df = _crafted_df()
    prepared = replay._prepare(df)

    parity = [(s.index, s.signal, s.reason) for s in replay._build_schedule(prepared)]
    reference = reference_live_schedule(prepared, CONFIG)

    assert parity == reference
    assert len(parity) >= 2  # 최소 1 매수 + 1 매도


def test_parity_schedule_matches_live_reference_across_random_walks():
    replay = GoldenCrossParityReplay(CONFIG)
    for seed in (0, 1, 2, 3, 5, 6):
        prepared = replay._prepare(_walk_df(seed))
        parity = [(s.index, s.signal, s.reason) for s in replay._build_schedule(prepared)]
        reference = reference_live_schedule(prepared, CONFIG)
        assert parity == reference, f"parity != live reference for seed={seed}"


# ==================== (B) 시그널이 실제로 발화하고 FSM 사유를 가짐 ====================


def test_crafted_path_fires_fsm_driven_buy_and_sell():
    replay = GoldenCrossParityReplay(CONFIG)
    schedule = replay.build_signal_schedule(_crafted_df())

    buys = [s for s in schedule if s.signal == "buy"]
    sells = [s for s in schedule if s.signal == "sell"]

    assert len(buys) >= 1
    assert len(sells) >= 1
    assert all(s.reason in BUY_REASONS for s in buys)
    assert all(s.reason in FSM_EXIT_REASONS for s in sells)

    # 단일 포지션: 매수/매도가 교대로만 발생(연속 동일 시그널 없음)
    kinds = [s.signal for s in schedule]
    assert all(a != b for a, b in zip(kinds, kinds[1:]))
    assert kinds[0] == "buy"


# ==================== (C) 실행: 체결/비용/성과 집계 ====================


def test_parity_run_executes_and_aggregates_result():
    replay = GoldenCrossParityReplay(CONFIG)
    df = _crafted_df()
    schedule = replay.build_signal_schedule(df)
    sell_count = sum(1 for s in schedule if s.signal == "sell")

    result = replay.run("091160", df, BacktestConfigDTO(initial_capital=Decimal("10000000")))

    # 완료 거래 수 = 매수 뒤 발생한 매도 수
    assert result.total_trades == sell_count
    assert result.execution_timing == "same_close"
    assert len(result.trades) == len(schedule) // 2 or len(result.trades) >= sell_count
    # crafted 경로는 익절 청산 1건
    exit_reasons = {t.exit_reason for t in result.trades if t.exit_reason}
    assert exit_reasons == {"take_profit"}
    # 비용/손익 반영으로 최종 자본이 초기와 달라짐
    assert result.final_capital != Decimal("10000000")


def test_parity_run_empty_universe_guard():
    replay = GoldenCrossParityReplay(CONFIG)
    empty = pd.DataFrame({c: [] for c in ["timestamp", "open", "high", "low", "close", "volume"]})
    try:
        replay.run("091160", empty)
    except ValueError:
        return
    raise AssertionError("expected ValueError on empty OHLCV")
