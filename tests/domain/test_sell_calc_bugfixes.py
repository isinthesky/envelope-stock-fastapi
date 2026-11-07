"""매도 분석/표시 계산 버그 묶음 회귀 테스트 (2026-11-06).

1. 52주 신고가: 오늘 고가를 제외한 직전 251 거래일 고가와 비교
2. 거래량 피크 보너스 이중 가산 제거 (indicators + sell_score_rules)
3. 매도 점수 정규화 분모: 데이터 가용성 기준 고정 max 합
4. 트레일링 거리: 전략 설정값 사용(기본 0.07은 미전달 시만)
5. 85% 수익 보호: 최소 피크 수익 가드
6/7. holdings.js: final_stage 표시 + 보유 중 최고가 전달
8. 현금계획 비중 상수 단일 소스
9. 매도 검증 지표: HOLD 대비 순효과(놓친 상승 + 비용 반영)
"""

from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from src.application.common.indicators import TechnicalIndicators
from src.application.domain.strategy.analysis_history_validation import (
    ForwardClose,
    SellRecommendationObservation,
    default_sell_cost_rate,
    evaluate_sell_recommendations,
    render_sell_validation_markdown,
)
from src.application.domain.strategy.dto import (
    CASH_PLAN_BASE_SELL_RATIOS,
    SELL_STAGE_INFO,
    SELL_STAGE_RATIOS,
    SellStageEnum,
    format_ratio_range,
)
from src.application.domain.strategy.portfolio_cash_planner import PortfolioCashPlanner
from src.application.domain.strategy.sell_score_rules import VOLUME_PEAK_BONUS
from src.application.domain.strategy.sell_strategy_service import (
    DEFAULT_TRAILING_STOP_DISTANCE,
    PROFIT_PROTECTION_MIN_PEAK_PROFIT,
    SellStrategyService,
)
from src.settings.sell_score_settings import SellScoreSettings

REPO_ROOT = Path(__file__).resolve().parents[2]


def _svc() -> SellStrategyService:
    return SellStrategyService(session=None, sell_score_settings=SellScoreSettings())


# ---------- 1. 52주 신고가 ----------
def _rising_df(n: int = 120) -> pd.DataFrame:
    # 매일 고가가 종가보다 2 높게 형성되는 상승 추세. 오늘 종가 > 어제까지 모든 고가.
    closes = [100.0 + i * 3 for i in range(n)]
    highs = [c + 2.0 for c in closes]
    return pd.DataFrame({"close": closes, "high": highs})


def test_52week_high_detected_when_close_breaks_prior_highs_below_today_high() -> None:
    df = _rising_df()
    close = float(df["close"].iloc[-1])
    assert close < float(df["high"].iloc[-1])  # 종가 != 당일 고가 (기존 버그 조건)

    is_new_high, score, reason, note = _svc()._check_52week_high("X", close, df)

    assert is_new_high is True
    assert score == 10.0
    assert note == "raw"
    assert "신고가 경신" in reason


def test_52week_reference_excludes_today_and_caps_lookback_to_251_prior_sessions() -> None:
    n = 300
    highs = [1000.0] + [100.0] * (n - 1)  # 아주 오래된 고점(> 251 세션 전)은 제외
    highs[-1] = 500.0  # 오늘 고가는 기준에서 제외
    df = pd.DataFrame({"close": [100.0] * n, "high": highs})

    assert SellStrategyService._prior_52week_high(df) == 100.0


def test_52week_not_new_high_when_close_below_prior_high() -> None:
    df = _rising_df()
    df.loc[df.index[-1], "close"] = float(df["high"].iloc[-2]) - 1.0
    is_new_high, score, _, _ = _svc()._check_52week_high("X", float(df["close"].iloc[-1]), df)
    assert is_new_high is False
    assert score == 5.0  # 근접(>= 95%)


# ---------- 2. 거래량 피크 이중 가산 ----------
def test_volume_peak_indicator_no_longer_adds_bonus() -> None:
    is_peak, score, reasons = TechnicalIndicators.check_volume_peak_signal(
        current_price=105.0,
        prev_price=100.0,
        current_volume=350,
        volume_ma_20=100.0,
    )
    assert is_peak is True
    assert score == 10.0  # 구간 점수만 (과거 15 = 10 + 5)
    assert any("피크 신호" in r for r in reasons)


def _score(svc: SellStrategyService, **overrides):
    kwargs = dict(
        stoch_k=60.0,
        stoch_d=55.0,
        prev_stoch_k=58.0,
        prev_stoch_d=54.0,
        rsi=60.0,
        volume_ratio=1.0,
        adx=30.0,
        plus_di=18.0,
        minus_di=20.0,
        is_death_cross=False,
        current_price=10000,
        ma_short=9900,
        ma_long=9500,
        ma_gap_ratio=4.2,
    )
    kwargs.update(overrides)
    return svc.calculate_sell_score(**kwargs)


def test_volume_peak_bonus_counted_once_in_sell_score() -> None:
    svc = _svc()
    _, peak_score, _ = TechnicalIndicators.check_volume_peak_signal(
        current_price=105.0, prev_price=100.0, current_volume=350, volume_ma_20=100.0
    )
    result = _score(
        svc,
        volume_ratio=3.5,
        volume_peak_score=peak_score,
        is_volume_peak=True,
    )
    # volume_ratio 3.5 → 15 (mid 2.5), peak tier 10 → max(15,10) + 5 = 20 (과거 15+... 이중 가산)
    assert result.score_breakdown["volume_score"] == 15.0 + VOLUME_PEAK_BONUS
    assert result.score_breakdown["volume_peak_score"] == 10.0


# ---------- 3. 정규화 분모 ----------
def test_available_max_is_independent_of_indicator_values() -> None:
    svc = _svc()
    common = dict(
        high_52week_score=0.0,
        personal_buy_days_5d=1,
        personal_buy_ratio_5d_to_volume=0.01,
        market_credit_change_ratio=0.0,
        market_credit_recent_high_ratio=0.5,
    )
    quiet = _score(svc, recent_5d_personal_net_buy=-1000, **common)
    hot = _score(
        svc,
        recent_5d_personal_net_buy=150000,
        volume_ratio=3.5,
        volume_peak_score=10.0,
        is_volume_peak=True,
        is_52week_high=True,
        stoch_k=90.0,
        risk_combo_peak=True,
        risk_combo_extreme=True,
        **common,
    )
    c = SellScoreSettings()
    expected = (
        c.stoch_weight
        + c.rsi_weight
        + c.volume_weight
        + VOLUME_PEAK_BONUS
        + 10.0  # 52주
        + c.personal_flow_weight
        + c.market_credit_weight
        + c.adx_weight
        + c.ma_weight
        + 3.0  # MA 갭 축소
        + c.cross_bonus
        + 5.0  # 신고가+과매수
        + c.risk_combo_weight
    )
    assert quiet.available_max == pytest.approx(expected)
    assert hot.available_max == pytest.approx(expected)


def test_available_max_excludes_rules_without_input_data() -> None:
    svc = _svc()
    result = _score(svc, volume_ratio=None, adx=None)
    c = SellScoreSettings()
    expected = c.stoch_weight + c.rsi_weight + c.ma_weight + 3.0 + c.cross_bonus
    assert result.available_max == pytest.approx(expected)


def test_firing_bonus_no_longer_inflates_normalized_score() -> None:
    svc = _svc()
    result = _score(
        svc,
        stoch_k=90.0,
        volume_ratio=3.5,
        volume_peak_score=10.0,
        is_volume_peak=True,
    )
    assert result.normalized_score == pytest.approx(
        result.total_score / result.available_max * 100, abs=0.01
    )
    # 피크 미발동이어도 거래량 max(weight+5)는 분모에 포함
    no_peak = _score(svc, stoch_k=90.0, volume_ratio=3.5)
    assert no_peak.available_max == result.available_max


# ---------- 4. 트레일링 거리 ----------
@pytest.mark.parametrize(
    ("distance", "drawdown", "expected"),
    [
        (0.05, 0.06, SellStageEnum.EXIT_ALL),  # 보수형: 6% 하락이면 발동
        (0.10, 0.08, SellStageEnum.REDUCE_1),  # 공격형: 8% 하락은 미발동 (과거 0.07로 발동)
        (None, 0.08, SellStageEnum.EXIT_ALL),  # 미전달 시 기본 0.07
        (None, 0.06, SellStageEnum.REDUCE_1),
    ],
)
def test_trailing_stop_uses_configured_distance(distance, drawdown, expected) -> None:
    stage, _ = _svc()._apply_position_risk_stage(
        SellStageEnum.REDUCE_1,
        is_take_profit_triggered=False,
        trailing_stop_activated=True,
        drawdown_from_high=drawdown,
        trailing_stop_distance=distance,
    )
    assert stage == expected


def test_default_trailing_distance_matches_risk_config_default() -> None:
    from src.application.domain.strategy.dto import GoldenCrossRiskConfig

    assert DEFAULT_TRAILING_STOP_DISTANCE == GoldenCrossRiskConfig().trailing_stop_distance == 0.07


# ---------- 5. 85% 수익 보호 최소 피크 ----------
def _simple(entry: float, high: float, cur: float) -> dict:
    return _svc().compute_simple_sell_signal(
        df=pd.DataFrame({"close": [entry, high, cur]}),
        rsi=50.0,
        current_price=cur,
        entry_price=entry,
        highest_price=high,
    )


def test_profit_protection_ignored_for_tiny_peak_profit() -> None:
    out = _simple(100.0, 101.0, 100.5)  # peak +1%, 현재 +0.5% (< 85%)
    assert out["should_sell"] is False
    assert not any("85% 수익 보호" in r for r in out["reasons"])


def test_profit_protection_fires_above_min_peak_profit() -> None:
    assert PROFIT_PROTECTION_MIN_PEAK_PROFIT == 0.05
    out = _simple(100.0, 110.0, 105.0)  # peak +10%, 현재 +5% (< 8.5%)
    assert out["should_sell"] is True
    assert any("85% 수익 보호" in r for r in out["reasons"])


# ---------- 6/7. holdings.js ----------
def test_holdings_js_displays_final_stage_and_sends_highest_price() -> None:
    js = (REPO_ROOT / "static/js/pages/holdings.js").read_text(encoding="utf-8")
    assert "d.final_stage || d.sell_stage" in js
    assert "final_ratio_min" in js
    assert "highest_price=" in js
    # 단계 판정에 rule stage를 직접 쓰지 않는다
    assert "const stg = d.sell_stage" not in js


# ---------- 8. 현금계획 비중 ----------
def test_cash_plan_base_ratio_single_source() -> None:
    class _Item:
        symbol = "A"
        name = None
        market = None
        sell_stage = "REDUCE_2"
        final_stage = "REDUCE_2"
        sell_reasons: list = []
        entry_price = None
        current_price = None
        highest_price = None
        overbought_sell_blocked = True  # 긴급도 상향(score>=60) 회피 → 기본 비중 그대로

    plan = PortfolioCashPlanner().build([_Item()])
    assert plan.actions[0].suggested_sell_ratio == CASH_PLAN_BASE_SELL_RATIOS["REDUCE_2"] == 0.50


def test_stage_info_text_generated_from_stage_ratios() -> None:
    for stage in SellStageEnum:
        assert SELL_STAGE_INFO[stage.value]["ratio"] == format_ratio_range(
            *SELL_STAGE_RATIOS[stage]
        )
    assert SELL_STAGE_INFO["REDUCE_2"]["action"] == "30~40% 매도 권장"


# ---------- 9. 매도 검증 순효과 ----------
def test_net_effect_penalizes_missed_upside_and_costs() -> None:
    base = datetime(2026, 1, 1)
    obs = [SellRecommendationObservation(1, "A", base, 100.0, "EXIT_ALL", 1.0, 1.0)]
    closes = {"A": [ForwardClose(base + timedelta(days=i), 100.0 + i) for i in range(1, 21)]}

    result = evaluate_sell_recommendations(obs, closes, cost_rate=0.002)
    row = result["observations"][0]

    assert row["avoided_loss_estimate"] == 0.0  # 과거 지표: 항상 >= 0
    assert row["missed_upside_estimate"] == pytest.approx(0.10)
    assert row["net_effect_estimate"] == pytest.approx(-0.10 - 0.002)
    summary = result["stage_summary"][0]
    assert summary["avg_net_effect_estimate"] == pytest.approx(-0.102)
    assert summary["net_effect_positive_rate"] == 0.0
    assert summary["avg_hold_baseline_return"] == pytest.approx(0.10)
    assert "Net effect" in render_sell_validation_markdown(result)


def test_net_effect_hold_is_baseline_and_default_cost_from_schedule() -> None:
    base = datetime(2026, 1, 1)
    obs = [
        SellRecommendationObservation(1, "A", base, 100.0, "REDUCE_2", 0.3, 0.4),
        SellRecommendationObservation(2, "B", base, 100.0, "HOLD"),
    ]
    closes = {
        "A": [ForwardClose(base + timedelta(days=i), 100.0 - i) for i in range(1, 21)],
        "B": [ForwardClose(base + timedelta(days=i), 100.0 - i) for i in range(1, 21)],
    }
    result = evaluate_sell_recommendations(obs, closes)
    reduce_row, hold_row = result["observations"]
    cost = default_sell_cost_rate(base.date())

    from src.application.domain.backtest.cost_schedule import get_backtest_cost_schedule

    schedule = get_backtest_cost_schedule(base.date())
    assert cost == pytest.approx(
        float(
            schedule.sell_tax_rate
            + schedule.default_commission_rate
            + schedule.default_slippage_rate
        )
    )
    assert reduce_row["net_effect_estimate"] == pytest.approx(0.10 * 0.35 - cost * 0.35)
    assert hold_row["net_effect_estimate"] == 0.0
    assert result["hold_baseline_avg_return"] == pytest.approx(-0.10)


class _FlatLoader:
    async def load_ohlcv_dataframe(self, **kwargs):
        _ = kwargs
        prices = [100.0] * 180
        return pd.DataFrame(
            {
                "timestamp": pd.date_range("2024-01-01", periods=len(prices), freq="D"),
                "open": prices,
                "high": prices,
                "low": prices,
                "close": prices,
                "volume": [1_000_000] * len(prices),
            }
        )


async def _none(*args, **kwargs):
    _ = args, kwargs
    return None


@pytest.mark.parametrize(("distance", "expected"), [(0.10, False), (None, True)])
async def test_analyze_sell_signal_forwards_trailing_distance(
    monkeypatch: pytest.MonkeyPatch, distance, expected
) -> None:
    svc = _svc()
    monkeypatch.setattr(svc, "_get_data_loader", lambda: _FlatLoader())
    monkeypatch.setattr(svc, "_get_personal_flow_data", _none)
    monkeypatch.setattr(svc, "_get_market_credit_trend", _none)

    # 현재가 100, 최고가 108.7 → 고점 대비 약 8% 하락: 기본 0.07이면 발동, 0.10이면 미발동
    result = await svc.analyze_sell_signal(
        symbol="005930",
        highest_price=108.7,
        trailing_stop_activated=True,
        use_scoring=False,
        sell_mode="legacy",
        trailing_stop_distance=distance,
    )

    fired = any("트레일링 스탑 발동" in r for r in result.sell_stage_reasons)
    assert fired is expected


def test_research_52week_window_matches_live_constant() -> None:
    from src.application.domain.strategy import sell_rule_research_service as research
    from src.application.domain.strategy.sell_strategy_service import (
        HIGH_52WEEK_LOOKBACK_SESSIONS,
    )

    assert research._PRIOR_52WEEK_SESSIONS == HIGH_52WEEK_LOOKBACK_SESSIONS - 1
