# -*- coding: utf-8 -*-
"""전략 계산식 blind-spot 수정 회귀 테스트 (#1,#6,#7,#9 + fear-window).

근거: docs/archive/IMPROVEMENT_PLAN_strategy_calc.md
"""
import pandas as pd
import pytest

from src.application.common.indicators import TechnicalIndicators as TI
from src.application.domain.strategy.sell_strategy_service import SellStrategyService


# Wilder(1978) 표준 예시 종가 (첫 RSI ≈ 70.53 @ 15번째 종가)
WILDER_CLOSES = [
    44.34,
    44.09,
    44.15,
    43.61,
    44.33,
    44.83,
    45.10,
    45.42,
    45.84,
    46.08,
    45.89,
    46.03,
    45.61,
    46.28,
    46.28,
    46.00,
    46.03,
    46.41,
    46.22,
    45.64,
    46.21,
    46.25,
    45.71,
    46.45,
    45.78,
]


# ---------- #1 시장 공포 필터 ----------
def test_fear_true_on_crash_with_bandwidth_expansion():
    closes = [100.0] * 25 + [90.0, 85.0, 80.0, 74.0, 68.0]
    assert TI.is_market_fear_by_bollinger(closes) is True


def test_fear_false_on_calm():
    closes = [100.0 + (i % 2) * 0.1 for i in range(30)]
    assert TI.is_market_fear_by_bollinger(closes) is False


def test_fear_false_below_min_length():
    assert TI.is_market_fear_by_bollinger([100.0] * 24) is False


def test_fear_prev_bws_populated_regression():
    # 버그 시 prev_bws가 항상 비어 bw>bw*1.10 → 영원히 False.
    closes = [100.0] * 25 + [92.0, 87.0, 81.0, 74.0, 66.0]
    assert TI.is_market_fear_by_bollinger(closes) is True


# ---------- #3 fear-window ----------
def test_fear_recent_window_detects_prior_fear():
    # 공포가 window 이내(마지막에서 2일 전)에 발생 → True
    closes = [100.0] * 25 + [90.0, 85.0, 80.0, 74.0, 68.0] + [69.0, 70.0]
    assert TI.is_market_fear_recent(closes, window=7) is True


def _regime_df(closes, timestamps):
    import pandas as pd

    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": [1000] * len(closes),
        }
    )


def test_market_regime_guard_fail_open(monkeypatch):
    # 레짐 하드게이트는 실 OHLC 벤치·신선 데이터일 때만 판정, 그 외 fail-open(True)
    from datetime import datetime, timedelta, timezone

    from src.application.domain.strategy import buy_strategy_service as mod

    now = datetime.now(timezone.utc)
    up = [float(x) for x in range(1, 251)]
    down = [float(x) for x in range(250, 0, -1)]
    fresh = [now - timedelta(days=250 - i) for i in range(250)]
    stale = [now - timedelta(days=400 - i) for i in range(250)]
    future = [now + timedelta(days=i) for i in range(250)]

    assert mod._market_regime_ok(None) is True  # 벤치 없음(프록시 불가) → fail-open
    assert (
        mod._market_regime_ok(_regime_df(up[:100], fresh[:100])) is True
    )  # 이력부족 → fail-open(워밍업)
    assert mod._market_regime_ok(_regime_df(up, stale)) is True  # stale → fail-open
    assert mod._market_regime_ok(_regime_df(down, future)) is True  # 미래 timestamp → fail-open

    # mode=ma 로 고정하면 close>MA200 판정이 결정적
    monkeypatch.setattr(mod.settings, "gc_regime_mode", "ma")
    assert mod._market_regime_ok(_regime_df(up, fresh)) is True  # 상승레짐 → 허용
    assert mod._market_regime_ok(_regime_df(down, fresh)) is False  # 하락레짐 → 차단


def test_market_uptrend_regime():
    # 마지막 종가 > MA200 → 상승레짐 True
    up = list(range(1, 251))  # 꾸준한 상승 → 마지막(250) > MA
    assert TI.is_market_uptrend([float(x) for x in up], 200) is True
    # 하락 추세 → 마지막 종가 < MA → False
    down = list(range(250, 0, -1))
    assert TI.is_market_uptrend([float(x) for x in down], 200) is False
    # 데이터 부족 → fail-open True
    assert TI.is_market_uptrend([100.0] * 50, 200) is True


def test_fear_recent_window_expires():
    calm_tail = [100.0 + (i % 2) * 0.1 for i in range(20)]
    closes = [100.0] * 25 + [90.0, 85.0, 80.0, 74.0, 68.0] + calm_tail
    assert TI.is_market_fear_recent(closes, window=3) is False


# ---------- #9 RSI Wilder 표준화 ----------
def test_wilder_seed_matches_reference():
    rsi = TI.calculate_rsi_series(pd.DataFrame({"close": WILDER_CLOSES[:15]}), 14).iloc[-1]
    assert abs(rsi - 70.53) < 0.5


def test_flat_series_rsi_is_neutral_50():
    # 무변동 시계열: gain/loss 모두 0 → RSI 100이 아니라 중립 50 (Codex 지적 보완)
    s = TI.calculate_rsi_series(pd.DataFrame({"close": [100.0] * 30}), 14)
    assert abs(s.iloc[-1] - 50.0) < 1e-9


def test_rsi_survives_single_nan_close():
    closes = WILDER_CLOSES.copy()
    closes[10] = float("nan")
    s = TI.calculate_rsi_series(pd.DataFrame({"close": closes}), 14)
    assert not pd.isna(s.iloc[-1])  # NaN이 tail을 오염시키지 않음


def test_scalar_matches_series_last_bar():
    series = TI.calculate_rsi_series(pd.DataFrame({"close": WILDER_CLOSES}), 14).iloc[-1]
    scalar = TI.calculate_rsi(WILDER_CLOSES, 14)
    assert abs(series - scalar) < 1e-9


def test_wilder_diverges_from_sma_after_smoothing():
    # seed bar에서는 Wilder==SMA. 이후 bar에서 재귀 smoothing으로 갈라져야 한다.
    df = pd.DataFrame({"close": WILDER_CLOSES})
    wilder_last = TI.calculate_rsi_series(df, 14).iloc[-1]
    ch = [
        WILDER_CLOSES[i] - WILDER_CLOSES[i - 1]
        for i in range(len(WILDER_CLOSES) - 14, len(WILDER_CLOSES))
    ]
    g = sum(max(c, 0) for c in ch) / 14
    loss_sum = sum(-c for c in ch if c < 0)
    sma_rsi = 100.0 if loss_sum == 0 else 100 - 100 / (1 + g / (loss_sum / 14))
    assert abs(wilder_last - sma_rsi) > 0.1


# ---------- #6 매도 하락확인 whipsaw ----------
def _svc():
    return SellStrategyService(session=None)


def test_single_tick_dip_does_not_trigger_sell():
    out = _svc().compute_simple_sell_signal(
        df=pd.DataFrame({"close": [100, 102, 104, 106, 108]}),
        rsi=75.0,
        current_price=107.0,
        entry_price=90.0,
        highest_price=108.0,
    )
    assert out["should_sell"] is False


# ---------- #7 매도 손절 재구성 ----------
def test_hard_stop_from_entry_triggers():
    out = _svc().compute_simple_sell_signal(
        df=pd.DataFrame({"close": [100, 99, 98, 84]}),
        rsi=50.0,
        current_price=84.0,
        entry_price=100.0,
    )
    assert out["should_sell"] is True
    assert any("하드 손절" in r for r in out["reasons"])


def test_no_orphan_20d_high_rule():
    # 20일 고점 -15% 고아 규칙 제거: 진입가 대비 이익이고 85% 미발동이면 매도 아님.
    out = _svc().compute_simple_sell_signal(
        df=pd.DataFrame({"close": [100 + i for i in range(30)]}),
        rsi=50.0,
        current_price=127.0,
        entry_price=100.0,
        highest_price=129.0,
    )
    assert out["should_sell"] is False


# ---------- #5 hybrid df ValueError ----------
@pytest.mark.asyncio
async def test_hybrid_with_nonempty_df_no_crash():
    from unittest.mock import AsyncMock, patch
    from datetime import datetime
    from src.application.domain.strategy.dto import SellSignalAnalysisDTO, SellStageEnum

    svc = _svc()
    df = pd.DataFrame({"close": [100.0 + i for i in range(25)]})
    legacy = SellSignalAnalysisDTO(
        symbol="005930",
        current_price=90,
        analyzed_at=datetime.now(),
        ma_short=80,
        ma_long=85,
        ma_gap_ratio=-1.0,
        is_death_cross=True,
        stoch_k=60.0,
        stoch_d=55.0,
        is_stoch_overbought=False,
        rsi=72.0,
        is_rsi_overbought=True,
        final_stage=SellStageEnum.REDUCE_1,
        sell_reasons=["legacy"],
    )
    with patch.object(svc, "analyze_sell_signal", new=AsyncMock(return_value=legacy)):
        result = await svc.analyze_sell_signal_hybrid(
            "005930",
            df=df,
            entry_price=100.0,
            highest_price=124.0,
        )
    assert set(result) == {"legacy", "simple", "hybrid_stage"}
