# -*- coding: utf-8 -*-
"""
Strategy Presets - 프로그래머가 정의하는 전략 프리셋 카탈로그

유저는 프리셋을 선택하고 심볼만 지정하면 전략을 생성할 수 있다.
config는 코드에서 관리하며 유저에게 노출하지 않는다.
"""

from dataclasses import dataclass, field

from src.application.domain.strategy.dto import GoldenCrossConfigDTO


@dataclass(frozen=True)
class StrategyPreset:
    """전략 프리셋 정의"""

    preset_id: str
    name: str
    description: str
    strategy_type: str
    config: GoldenCrossConfigDTO
    tags: list[str] = field(default_factory=list)
    risk_level: str = "medium"  # low, medium, high


# ==================== 프리셋 카탈로그 ====================

STRATEGY_PRESETS: dict[str, StrategyPreset] = {
    "gc_standard": StrategyPreset(
        preset_id="gc_standard",
        name="골든크로스 기본형",
        description="골든크로스(config MA 단기/장기) + Stochastic 과매도 매수. 기본 설정으로 안정적인 중기 추세추종.",
        strategy_type="golden_cross",
        config=GoldenCrossConfigDTO(),
        tags=["골든크로스", "중기", "추세추종"],
        risk_level="medium",
    ),
    "gc_aggressive": StrategyPreset(
        preset_id="gc_aggressive",
        name="골든크로스 공격형",
        description="넓은 MA갭 허용, 높은 손절/익절 비율. 변동성이 큰 종목에 적합.",
        strategy_type="golden_cross",
        config=GoldenCrossConfigDTO(
            stochastic_config={
                "k_period": 14,
                "d_period": 3,
                "oversold_threshold": 30.0,
                "recovery_threshold": 25.0,
                "strong_recovery_threshold": 35.0,
                "deep_oversold_threshold": 35.0,
                "require_momentum_turn": False,
            },
            risk_config={
                "use_stop_loss": True,
                "stop_loss_ratio": -0.10,
                "use_take_profit": True,
                "take_profit_ratio": 0.30,
                "use_trailing_stop": True,
                "trailing_stop_activation": 0.20,
                "trailing_stop_distance": 0.10,
                "max_hold_days": 90,
            },
            ma_gap_config={
                "min_gap_ratio": 0.0,
                "max_gap_ratio": 12.0,
            },
            position={
                "allocation_ratio": 0.15,
                "max_position_count": 7,
            },
        ),
        tags=["골든크로스", "공격형", "고변동"],
        risk_level="high",
    ),
    "gc_conservative": StrategyPreset(
        preset_id="gc_conservative",
        name="골든크로스 보수형",
        description="좁은 MA갭, 빠른 손절, 모멘텀 전환 필수. 안전한 진입을 선호하는 투자자용.",
        strategy_type="golden_cross",
        config=GoldenCrossConfigDTO(
            stochastic_config={
                "k_period": 14,
                "d_period": 3,
                "oversold_threshold": 20.0,
                "recovery_threshold": 15.0,
                "strong_recovery_threshold": 25.0,
                "deep_oversold_threshold": 25.0,
                "require_momentum_turn": True,
            },
            risk_config={
                "use_stop_loss": True,
                "stop_loss_ratio": -0.05,
                "use_take_profit": True,
                "take_profit_ratio": 0.15,
                "use_trailing_stop": True,
                "trailing_stop_activation": 0.10,
                "trailing_stop_distance": 0.05,
                "max_hold_days": 40,
            },
            ma_gap_config={
                "min_gap_ratio": 0.0,
                "max_gap_ratio": 5.0,
            },
            position={
                "allocation_ratio": 0.08,
                "max_position_count": 3,
            },
        ),
        tags=["골든크로스", "보수형", "안전"],
        risk_level="low",
    ),
}


def get_preset(preset_id: str) -> StrategyPreset | None:
    """프리셋 ID로 조회"""
    return STRATEGY_PRESETS.get(preset_id)


def list_presets() -> list[StrategyPreset]:
    """전체 프리셋 목록 반환"""
    return list(STRATEGY_PRESETS.values())
