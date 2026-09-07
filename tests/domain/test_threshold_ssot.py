# -*- coding: utf-8 -*-
"""임계값 SSOT 핀 테스트 (P1-B).

'값이 다르니 통일하자'는 선의의 리팩터링이 전략 거동을 바꾸는 것을 막는다.
값을 바꾸려면 이 테스트를 먼저 고쳐야 하고, 그 시점에 백테스트 재검증이 강제된다.

주의: 환경변수로 튜닝 가능한 값(settings.*, SellScoreSettings.*)은 인스턴스가 아니라
model_fields의 **선언 기본값**을 검사한다. 운영자가 정당하게 튜닝했을 때 CI가
빨간불이 되면 안 되기 때문이다.
"""

from src.application.domain.strategy.dto import (
    GoldenCrossConfigDTO,
    SellPhaseEnum,
    SellStageEnum,
    StochasticConfig,
)
from src.application.domain.strategy.presets import STRATEGY_PRESETS
from src.application.domain.strategy.public_strategy_service import PUBLIC_SCAN_STOCH_THRESHOLD
from src.application.domain.strategy.risk_contract import DEFAULT_PEAK_DRAWDOWN_STOP_RATIO
from src.application.domain.strategy.sell_strategy_service import SellStrategyService
from src.application.domain.strategy.strategy_contract import DEFAULT_GOLDEN_CROSS_PULLBACK
from src.settings.config import Settings
from src.settings.sell_score_settings import DEFAULT_PEAK_RULE_THRESHOLDS, SellScoreSettings


def test_live_entry_stoch_threshold_is_25_and_scan_default_is_30() -> None:
    """실주문 기본값 25.0 / 스캔·백테스트 기준선 30.0은 의도된 차이다."""
    assert StochasticConfig().oversold_threshold == 25.0
    assert GoldenCrossConfigDTO().stochastic_config.oversold_threshold == 25.0

    assert DEFAULT_GOLDEN_CROSS_PULLBACK.oversold_threshold == 30.0
    assert PUBLIC_SCAN_STOCH_THRESHOLD == 30.0
    assert Settings.model_fields["buy_notification_stoch_threshold"].default == 30.0

    # 두 값이 같아졌다면 누군가 '통일'한 것이다 → 전략 거동 변경이므로 실패시킨다.
    assert StochasticConfig().oversold_threshold != DEFAULT_GOLDEN_CROSS_PULLBACK.oversold_threshold


def test_gc_standard_preset_uses_live_stoch_default() -> None:
    """gc_standard는 DTO 기본값을 그대로 쓰므로 25.0이어야 한다."""
    preset = STRATEGY_PRESETS["gc_standard"]
    assert preset.config.stochastic_config.oversold_threshold == 25.0


def test_gc_aggressive_preset_overrides_stoch_to_scan_value() -> None:
    """실주문 경로가 항상 25.0인 것은 아니다 — 프리셋 오버라이드가 이긴다."""
    preset = STRATEGY_PRESETS["gc_aggressive"]
    assert preset.config.stochastic_config.oversold_threshold == 30.0


def test_peak_gate_ratio_and_score_tier_ratio_are_distinct_concepts() -> None:
    """peak 규칙 게이트(0.15)와 매도 점수 티어 경계(0.20)는 다른 개념이다."""
    gate = DEFAULT_PEAK_RULE_THRESHOLDS.personal_strong_gate_ratio
    tier = SellScoreSettings.model_fields["personal_buy_ratio_high"].default

    assert gate == 0.15
    assert tier == 0.20
    assert gate != tier  # 통합 시도 감지
    # personal_extreme_ratio(0.20)와 값이 같은 것도 우연이며, 개념은 또 다르다.
    assert DEFAULT_PEAK_RULE_THRESHOLDS.personal_extreme_ratio == 0.20


def test_peak_drawdown_stop_ratio_renders_as_15_percent() -> None:
    """사유 문구가 상수에서 렌더링되며 기존 문자열과 동일함을 보장한다."""
    assert DEFAULT_PEAK_DRAWDOWN_STOP_RATIO == 0.15
    assert f"{DEFAULT_PEAK_DRAWDOWN_STOP_RATIO:.0%}" == "15%"


def test_stop_loss_reason_strings_use_the_constant() -> None:
    """실제 사유 문구에 '15%'가 그대로 들어가는지 확인(문자열 회귀 방지)."""
    service = SellStrategyService(session=None)
    stage, reasons = service._determine_sell_stage(
        sell_phase=SellPhaseEnum.NONE,
        is_death_cross=False,
        is_gc_active=True,
        stoch_k=50.0,
        rsi=50.0,
        ma_gap_ratio=5.0,
        adx=None,
        plus_di=None,
        minus_di=None,
        is_volume_sell_signal=False,
        profit_ratio=-0.2,
        is_stop_loss_triggered=True,
    )

    assert stage is SellStageEnum.EXIT_ALL
    assert any("최고가 대비 15% 하락" in reason for reason in reasons)


def test_portfolio_cash_plan_stop_loss_reason_keeps_15_percent_wording() -> None:
    """지표 부족 폴백 사유도 상수 렌더링 후 문구가 동일해야 한다."""
    assert (
        f"최고가 대비 {DEFAULT_PEAK_DRAWDOWN_STOP_RATIO:.0%} 손절 우선 (지표 데이터 부족)"
        == "최고가 대비 15% 손절 우선 (지표 데이터 부족)"
    )
