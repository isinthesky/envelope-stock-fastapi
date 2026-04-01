from src.application.domain.strategy.dto import SellStageEnum
from src.application.domain.strategy.sell_strategy_service import SellStrategyService
from src.settings.sell_score_settings import SellScoreSettings


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


def test_personal_overheat_upgrades_stage_by_one_level() -> None:
    service = SellStrategyService(session=None)

    upgraded_stage, reasons = service._upgrade_stage_for_personal_overheat(
        stage=SellStageEnum.REDUCE_1,
        is_personal_buying_overheated=True,
    )

    assert upgraded_stage == SellStageEnum.REDUCE_2
    assert any("Stage 한 단계 강화" in reason for reason in reasons)


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
