import pandas as pd
import pytest

from src.application.domain.strategy.dto import SellPhaseEnum, SellScoreResultDTO, SellStageEnum
from src.application.domain.strategy.sell_strategy_service import SellStrategyService
from src.settings.sell_score_settings import SellScoreSettings


class _DummySellSignalDataLoader:
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
                "volume": [1000000] * len(prices),
            }
        )


def _stub_neutral_sell_dependencies(
    service: SellStrategyService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service, "_get_data_loader", lambda: _DummySellSignalDataLoader())
    monkeypatch.setattr(service, "_get_personal_flow_data", lambda symbol: _async_none())
    monkeypatch.setattr(service, "_get_market_credit_trend", lambda market: _async_none())
    monkeypatch.setattr(service, "_check_52week_high", lambda **kwargs: (False, 0.0, "", "raw"))
    monkeypatch.setattr(
        service,
        "_calculate_volume_indicators",
        lambda *args, **kwargs: {
            "current_volume": 1000000,
            "prev_volume": 1000000,
            "volume_ma_20": 1000000,
            "volume_ratio": 1.0,
            "is_volume_spike": False,
            "price_drop_ratio": 0.0,
            "is_volume_sell_signal": False,
            "volume_sell_reasons": [],
            "is_volume_peak": False,
            "volume_signal_type": "none",
            "volume_peak_reasons": [],
            "volume_peak_score": 0.0,
        },
    )
    monkeypatch.setattr(
        service,
        "_calculate_adx_indicators",
        lambda *args, **kwargs: {
            "adx": None,
            "plus_di": None,
            "minus_di": None,
            "is_strong_uptrend": False,
            "is_strong_downtrend": False,
        },
    )
    monkeypatch.setattr(service, "_analyze_sell_phase", lambda **kwargs: (SellPhaseEnum.NONE, []))
    monkeypatch.setattr(
        service,
        "calculate_sell_score",
        lambda **kwargs: SellScoreResultDTO(
            total_score=0.0,
            normalized_score=0.0,
            available_max=0.0,
            score_breakdown={},
            score_reasons=[],
            recommended_stage=SellStageEnum.HOLD,
        ),
    )


async def _async_none():
    return None


def test_personal_flow_overheated_when_recent_buying_is_concentrated() -> None:
    service = SellStrategyService(session=None)
    data = service._is_personal_buying_overheated(
        type(
            "PersonalFlow",
            (),
            {
                "days_positive_count": 5,
                "recent_5d_net_buy": 120000,
                "recent_5d_buy_ratio_to_volume": 0.24,
            },
        )()
    )

    is_overheated, reasons = data
    assert is_overheated is True
    assert len(reasons) >= 2


def test_calculate_sell_score_adds_personal_flow_score() -> None:
    settings = SellScoreSettings(
        personal_flow_weight=12.0,
        personal_buy_days_threshold=4,
        personal_buy_ratio_high=0.20,
        personal_buy_ratio_mid=0.10,
    )
    service = SellStrategyService(session=None, sell_score_settings=settings)

    result = service.calculate_sell_score(
        stoch_k=60.0,
        stoch_d=55.0,
        prev_stoch_k=58.0,
        prev_stoch_d=54.0,
        rsi=62.0,
        volume_ratio=1.1,
        adx=20.0,
        plus_di=18.0,
        minus_di=20.0,
        is_death_cross=False,
        current_price=10000,
        ma_short=9900,
        ma_long=9500,
        ma_gap_ratio=4.2,
        personal_buy_days_5d=5,
        personal_buy_ratio_5d_to_volume=0.25,
        recent_5d_personal_net_buy=150000,
    )

    assert result.score_breakdown["personal_flow_score"] == 12.0
    assert any("개인 수급" in reason for reason in result.score_reasons)


def test_calculate_sell_score_adds_market_credit_and_combo_bonus() -> None:
    settings = SellScoreSettings(
        personal_flow_weight=12.0,
        market_credit_weight=8.0,
        risk_combo_weight=6.0,
    )
    service = SellStrategyService(session=None, sell_score_settings=settings)

    result = service.calculate_sell_score(
        stoch_k=88.0,
        stoch_d=82.0,
        prev_stoch_k=90.0,
        prev_stoch_d=80.0,
        rsi=74.0,
        volume_ratio=1.8,
        adx=18.0,
        plus_di=16.0,
        minus_di=22.0,
        is_death_cross=False,
        current_price=10000,
        ma_short=9900,
        ma_long=9500,
        ma_gap_ratio=4.2,
        is_52week_high=True,
        high_52week_score=10.0,
        personal_buy_days_5d=5,
        personal_buy_ratio_5d_to_volume=0.25,
        recent_5d_personal_net_buy=150000,
        market_credit_change_ratio=0.011,
        market_credit_recent_high_ratio=0.996,
        risk_combo_peak=True,
        risk_combo_extreme=True,
    )

    assert result.score_breakdown["market_credit_score"] == 8.0
    assert result.score_breakdown["risk_combo_bonus"] == 6.0
    assert any("시장 신용" in reason for reason in result.score_reasons)


def test_overlay_stage_upgrade_is_limited_to_one_step() -> None:
    service = SellStrategyService(session=None)

    upgraded_stage, reasons = service._apply_overlay_stage_upgrade(
        SellStageEnum.REDUCE_1,
        is_personal_buying_overheated=True,
        overlay_signals={
            "risk_combo_peak": True,
            "risk_combo_extreme": True,
        },
    )

    assert upgraded_stage == SellStageEnum.REDUCE_2
    assert len([reason for reason in reasons if "Stage 한 단계 강화" in reason]) == 1
    assert any("고점권" in reason for reason in reasons)


def test_market_credit_alone_does_not_upgrade_stage() -> None:
    service = SellStrategyService(session=None)

    upgraded_stage, reasons = service._apply_overlay_stage_upgrade(
        SellStageEnum.HOLD,
        is_personal_buying_overheated=False,
        overlay_signals={
            "risk_combo_peak": False,
            "risk_combo_extreme": False,
            "research_credit_hot_personal_strong": False,
            "market_credit_hot": True,
        },
    )

    assert upgraded_stage == SellStageEnum.HOLD
    assert reasons == []


def test_take_profit_trigger_upgrades_final_stage_to_reduce_2() -> None:
    service = SellStrategyService(session=None)

    stage, reasons = service._apply_position_risk_stage(
        SellStageEnum.HOLD,
        is_take_profit_triggered=True,
        trailing_stop_activated=False,
        drawdown_from_high=None,
    )

    assert stage == SellStageEnum.REDUCE_2
    assert any("익절 목표" in reason for reason in reasons)


def test_trailing_stop_drawdown_upgrades_final_stage_to_exit_all() -> None:
    service = SellStrategyService(session=None)

    stage, reasons = service._apply_position_risk_stage(
        SellStageEnum.REDUCE_1,
        is_take_profit_triggered=False,
        trailing_stop_activated=True,
        drawdown_from_high=0.08,
    )

    assert stage == SellStageEnum.EXIT_ALL
    assert any("트레일링 스탑 발동" in reason for reason in reasons)


async def test_analyze_sell_signal_reflects_take_profit_in_final_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SellStrategyService(session=None)
    _stub_neutral_sell_dependencies(service, monkeypatch)

    result = await service.analyze_sell_signal(
        symbol="005930",
        entry_price=80.0,
        use_scoring=False,
    )

    assert result.is_take_profit_triggered is True
    assert result.sell_stage == SellStageEnum.HOLD.value
    assert result.final_stage == SellStageEnum.REDUCE_2
    assert result.final_ratio_min == 0.3
    assert result.final_ratio_max == 0.4
    assert any("익절 목표" in reason for reason in result.sell_stage_reasons)


async def test_analyze_sell_signal_reflects_trailing_stop_in_final_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SellStrategyService(session=None)
    _stub_neutral_sell_dependencies(service, monkeypatch)

    result = await service.analyze_sell_signal(
        symbol="005930",
        highest_price=110.0,
        trailing_stop_activated=True,
        use_scoring=False,
    )

    assert result.trailing_stop_activated is True
    assert result.drawdown_from_high == 0.0909
    assert result.sell_stage == SellStageEnum.HOLD.value
    assert result.final_stage == SellStageEnum.EXIT_ALL
    assert result.final_ratio_min == 1.0
    assert result.final_ratio_max == 1.0
    assert any("트레일링 스탑 발동" in reason for reason in result.sell_stage_reasons)


async def test_overlay_stage_upgrade_applied_at_most_once_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """회귀 방지: analyze_sell_signal 전 구간에서 오버레이 단계강화는 최대 1회만 적용.

    과거 rule stage(828)와 final stage(897) 양쪽에서 호출해 오버레이 1개가 매도단계를
    2단계 올리던 버그(문서/테스트 '최대 1회' 불변식 위반)를 고정한다.
    """
    service = SellStrategyService(session=None)
    _stub_neutral_sell_dependencies(service, monkeypatch)

    calls: list[int] = []
    original = service._apply_overlay_stage_upgrade

    def _counting(*args: object, **kwargs: object):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "_apply_overlay_stage_upgrade", _counting)

    await service.analyze_sell_signal(symbol="005930", use_scoring=True)

    assert len(calls) == 1


async def test_public_mode_skips_personal_flow_and_credit_overlays(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SellStrategyService(session=None)
    _stub_neutral_sell_dependencies(service, monkeypatch)

    async def _must_not_run(*args, **kwargs):
        _ = args, kwargs
        raise AssertionError("public technical-only analysis must skip overlays")

    monkeypatch.setattr(service, "_build_overlays", _must_not_run)

    result = await service.analyze_sell_signal(
        symbol="005930", use_scoring=True, include_overlays=False
    )

    assert result.personal_net_buy_latest is None
    assert result.market_credit_balance_million is None


async def test_hybrid_mode_applies_mechanical_floor_to_final_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sell_mode='hybrid'에서 85% 피크수익 보호 등 기계적 규칙이 final_stage에 반영된다.

    과거엔 reason 텍스트로만 남고 final_stage/비율이 HOLD로 남아 알림 심각도와
    근거가 불일치하던 갭을 고정한다.
    """
    service = SellStrategyService(session=None)
    _stub_neutral_sell_dependencies(service, monkeypatch)
    # 기계적 보호(85% 수익 보호)가 켜진 simple 신호를 주입
    monkeypatch.setattr(
        service,
        "compute_simple_sell_signal",
        lambda *args, **kwargs: {
            "should_sell": True,
            "reasons": ["85% 수익 보호 트리거 (peak=8.0%, 현재=-2.0%)"],
        },
    )

    result = await service.analyze_sell_signal(
        symbol="005930", use_scoring=True, sell_mode="hybrid"
    )

    assert result.final_stage == SellStageEnum.REDUCE_2
    assert result.final_ratio_min == 0.3
    assert result.final_ratio_max == 0.4
    assert any("기계적 보호" in r for r in result.sell_stage_reasons)


async def test_legacy_mode_ignores_mechanical_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sell_mode='legacy'는 기계적 floor 영향 없이 HOLD 유지(모드 게이팅 확인)."""
    service = SellStrategyService(session=None)
    _stub_neutral_sell_dependencies(service, monkeypatch)
    monkeypatch.setattr(
        service,
        "compute_simple_sell_signal",
        lambda *args, **kwargs: {
            "should_sell": True,
            "reasons": ["85% 수익 보호 트리거 (peak=8.0%, 현재=-2.0%)"],
        },
    )

    result = await service.analyze_sell_signal(
        symbol="005930", use_scoring=True, sell_mode="legacy"
    )

    assert result.final_stage == SellStageEnum.HOLD
