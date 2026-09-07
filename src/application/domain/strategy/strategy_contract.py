# -*- coding: utf-8 -*-
"""Canonical golden-cross pullback strategy contract."""

from dataclasses import dataclass
from enum import StrEnum

from src.application.domain.strategy.dto import SellStageEnum

# 매도 Stage 강도 순서 (약함 → 강함) 단일 출처.
# sell_strategy_service 여러 곳에 중복되어 있던 리터럴을 이 상수로 통합한다.
SELL_STAGE_ORDER: tuple[SellStageEnum, ...] = (
    SellStageEnum.HOLD,
    SellStageEnum.REDUCE_1,
    SellStageEnum.REDUCE_2,
    SellStageEnum.EXIT_ALL,
)


def market_credit_label(market: str | None) -> str:
    """시장 코드를 KOFIA 시장 신용 라벨로 매핑한다 (공유 헬퍼)."""
    market_key = (market or "").upper()
    if market_key == "KOSPI":
        return "유가증권"
    if market_key == "KOSDAQ":
        return "코스닥"
    return "전체"


class GoldenCrossScanState(StrEnum):
    NOT_GC = "NOT_GC"
    GC_ACTIVE = "GC_ACTIVE"
    WAITING_FOR_PULLBACK = "WAITING_FOR_PULLBACK"
    READY_TO_BUY = "READY_TO_BUY"
    BUY_INTEREST = "BUY_INTEREST"
    OPTIMAL_BUY = "OPTIMAL_BUY"
    # [#2/#3] 시장 공포 윈도우 중 개별 과매도로 진입하는 비-GC 후보 (fear-buy)
    FEAR_BUY = "FEAR_BUY"


class GoldenCrossTradeSignal(StrEnum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class GoldenCrossTransitionReason(StrEnum):
    GOLDEN_CROSS_DETECTED = "golden_cross_detected"
    GC_INVALIDATED = "gc_invalidated"
    GC_INVALIDATED_DURING_READY = "gc_invalidated_during_ready"
    PULLBACK_DETECTED = "pullback_detected"
    STOCH_RECOVERY_CROSSOVER = "stoch_recovery_crossover"
    STOCH_STRONG_RECOVERY = "stoch_strong_recovery"
    UNKNOWN_STATE_RESET = "unknown_state_reset"


class GoldenCrossRiskExitReason(StrEnum):
    DEAD_CROSS = "dead_cross"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    TRAILING_STOP = "trailing_stop"
    MAX_HOLD = "max_hold"
    PARTIAL_TAKE_PROFIT_1 = "partial_take_profit_1"
    PARTIAL_TAKE_PROFIT_2 = "partial_take_profit_2"
    BREAKEVEN = "breakeven"


@dataclass(frozen=True, slots=True)
class GoldenCrossPullbackParameters:
    """스캔/추천/알림/백테스트 기준선 파라미터.

    NOTE(P1-B): 이 세트의 ``oversold_threshold``(30.0)와
    ``strategy.dto.StochasticConfig.oversold_threshold``(25.0)가 다른 것은 drift가 아니라
    **판정 경로가 다르기 때문**이다. 한쪽으로 통일하면 전략 거동이 바뀐다. 값 변경 금지.
      - 30.0 (이 세트) : 스캔/추천/알림/백테스트 기준선.
        strategy_router / buy_strategy_service / strategy_service /
        public_strategy_service(PUBLIC_SCAN_STOCH_THRESHOLD) /
        recommendation_scan_service / recommendation.rule_set_validation_service
        (_UNIVERSE_STOCH_THRESHOLD) / settings.buy_notification_stoch_threshold /
        backtest generators 가 이 기준을 쓴다.
      - 25.0 (StochasticConfig 기본값) : 프리셋이 stochastic_config를 지정하지 않았을 때의
        실주문 기본값. GoldenCrossConfigDTO → GoldenCrossStateMachine → golden_cross_engine
        (실계좌 주문 경로)으로 이어진다.
      - 단, 실주문 경로가 항상 25.0인 것은 아니다. presets.gc_aggressive는
        stochastic_config에 oversold_threshold=30.0을 명시한다(프리셋별 오버라이드).

    핀 테스트: tests/domain/test_threshold_ssot.py
    """

    short_period: int = 55
    long_period: int = 165
    stoch_k_period: int = 14
    stoch_d_period: int = 3
    # 스캔/추천/백테스트 기준 과매도 임계값. 실주문 기본값(StochasticConfig 25.0)과 의도적으로 다르다.
    oversold_threshold: float = 30.0
    recovery_threshold: float = 20.0
    strong_recovery_threshold: float = 30.0
    min_ma_gap: float = 0.0
    max_ma_gap: float = 8.0
    min_pullback_bars: int = 2
    min_reentry_cooldown_bars: int = 5


@dataclass(frozen=True, slots=True)
class GoldenCrossScanContext:
    is_gc_active: bool
    stoch_k: float
    stoch_d: float
    stoch_threshold: float
    ma_gap_ratio: float
    prev_stoch_k: float | None = None
    recent_oversold: bool = False
    recovery_threshold: float = 20.0
    strong_recovery_threshold: float = 30.0
    require_momentum_turn: bool = True
    min_ma_gap: float = 0.0
    max_ma_gap: float = 8.0


DEFAULT_GOLDEN_CROSS_PULLBACK = GoldenCrossPullbackParameters()
GOLDEN_CROSS_SCAN_STATE_ORDER: tuple[GoldenCrossScanState, ...] = (
    GoldenCrossScanState.OPTIMAL_BUY,
    GoldenCrossScanState.BUY_INTEREST,
    GoldenCrossScanState.READY_TO_BUY,
    GoldenCrossScanState.WAITING_FOR_PULLBACK,
    GoldenCrossScanState.GC_ACTIVE,
    GoldenCrossScanState.NOT_GC,
)
GOLDEN_CROSS_BUY_CANDIDATE_STATES: tuple[GoldenCrossScanState, ...] = (
    GoldenCrossScanState.OPTIMAL_BUY,
    GoldenCrossScanState.BUY_INTEREST,
    GoldenCrossScanState.READY_TO_BUY,
)


class GoldenCrossStrategyContract:
    @staticmethod
    def is_buy_entry_ready(context: GoldenCrossScanContext) -> bool:
        """Return whether a pullback recovery satisfies the canonical entry rule."""
        return (
            GoldenCrossStrategyContract.classify_scan_state(context)
            == GoldenCrossScanState.OPTIMAL_BUY
        )

    @staticmethod
    def classify_scan_state(context: GoldenCrossScanContext) -> GoldenCrossScanState:
        if not context.is_gc_active:
            return GoldenCrossScanState.NOT_GC

        if context.stoch_k < context.stoch_threshold:
            return GoldenCrossScanState.READY_TO_BUY

        if context.stoch_k >= 50:
            return GoldenCrossScanState.GC_ACTIVE

        is_healthy_trend = context.min_ma_gap <= context.ma_gap_ratio <= context.max_ma_gap
        is_momentum_turning = (
            context.stoch_k > context.stoch_d if context.require_momentum_turn else True
        )
        is_rising = context.prev_stoch_k is None or context.stoch_k > context.prev_stoch_k
        recovered_from_pullback = (
            context.recent_oversold and context.stoch_k >= context.recovery_threshold and is_rising
        )
        strong_recovery = (
            context.recent_oversold
            and context.stoch_k >= context.strong_recovery_threshold
            and is_rising
        )

        if (
            (recovered_from_pullback or strong_recovery)
            and is_momentum_turning
            and is_healthy_trend
        ):
            return GoldenCrossScanState.OPTIMAL_BUY

        if context.recent_oversold and is_healthy_trend and (is_rising or is_momentum_turning):
            return GoldenCrossScanState.BUY_INTEREST

        return GoldenCrossScanState.WAITING_FOR_PULLBACK

    @staticmethod
    def buy_candidate_state_values() -> list[str]:
        return [state.value for state in GOLDEN_CROSS_BUY_CANDIDATE_STATES]
