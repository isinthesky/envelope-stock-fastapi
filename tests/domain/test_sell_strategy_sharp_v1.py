from src.application.domain.strategy.dto import SellPhaseEnum, SellStageEnum
from src.application.domain.strategy.sell_strategy_service import SellStrategyService


def test_sharp_v1_reduces_winner_before_adx_hold_filter() -> None:
    service = SellStrategyService(session=None)

    stage, reasons = service._determine_sell_stage(
        sell_phase=SellPhaseEnum.NONE,
        is_death_cross=False,
        is_gc_active=True,
        stoch_k=87.0,
        rsi=75.0,
        ma_gap_ratio=14.0,
        adx=32.0,
        plus_di=35.0,
        minus_di=15.0,
        is_volume_sell_signal=False,
        profit_ratio=0.11,
        is_volume_spike=True,
        is_volume_peak=True,
        is_stoch_dead_cross=True,
        is_52week_high=True,
        high_52week_ratio=1.0,
        dynamic_stoch_threshold=65.0,
        dynamic_rsi_threshold=68.0,
        name="삼성전자",
        market="KOSPI",
    )

    assert stage == SellStageEnum.REDUCE_1
    assert any("[sharp v1]" in reason for reason in reasons)


def test_sharp_v1_applies_stricter_thresholds_to_leveraged_etf_like_products() -> None:
    service = SellStrategyService(session=None)

    common_kwargs = dict(
        sell_phase=SellPhaseEnum.NONE,
        is_death_cross=False,
        is_gc_active=True,
        stoch_k=78.0,
        rsi=71.0,
        ma_gap_ratio=9.0,
        adx=31.0,
        plus_di=28.0,
        minus_di=14.0,
        is_volume_sell_signal=False,
        profit_ratio=0.06,
        is_volume_spike=True,
        is_volume_peak=False,
        is_stoch_dead_cross=False,
        is_52week_high=False,
        high_52week_ratio=0.985,
        dynamic_stoch_threshold=70.0,
        dynamic_rsi_threshold=70.0,
    )

    stock_stage, _ = service._determine_sell_stage(
        **common_kwargs,
        name="삼성전자",
        market="KOSPI",
    )
    etf_stage, reasons = service._determine_sell_stage(
        **common_kwargs,
        name="KODEX 레버리지",
        market="ETF",
    )

    assert stock_stage == SellStageEnum.HOLD
    assert etf_stage == SellStageEnum.REDUCE_1
    assert any("ETF/레버리지" in reason for reason in reasons)
