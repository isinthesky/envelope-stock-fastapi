# -*- coding: utf-8 -*-
"""
Golden Cross State Machine - 골든크로스 상태 머신

상태 전이:
WAITING_FOR_GC → WAITING_FOR_PULLBACK → READY_TO_BUY → IN_POSITION

진입 조건:
1. 단기 MA > 장기 MA (골든크로스 발생)
2. Stoch K < 25 (풀백/과매도)
3. Stoch K > 20 (회복) 또는 Stoch K > 30 (강한 회복)

청산 조건:
1. 단기 MA < 장기 MA (데드크로스)
2. 손절/익절/트레일링 스탑
3. 최대 보유 기간 초과
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import NamedTuple

from src.adapters.database.models.strategy_symbol_state import SymbolState
from src.application.domain.strategy.dto import (
    GoldenCrossConfigDTO,
)
from src.application.domain.strategy.strategy_contract import (
    GoldenCrossScanContext,
    GoldenCrossRiskExitReason,
    GoldenCrossStrategyContract,
    GoldenCrossTradeSignal,
    GoldenCrossTransitionReason,
)


class Signal(str, Enum):
    """시그널 유형"""

    BUY = GoldenCrossTradeSignal.BUY.value
    SELL = GoldenCrossTradeSignal.SELL.value
    HOLD = GoldenCrossTradeSignal.HOLD.value


@dataclass
class IndicatorSnapshot:
    """지표 스냅샷"""

    timestamp: datetime
    close: Decimal
    ma_short: Decimal
    ma_long: Decimal
    stoch_k: float
    stoch_d: float

    @property
    def is_gc_active(self) -> bool:
        """골든크로스 활성 상태"""
        return self.ma_short > self.ma_long


class StateTransition(NamedTuple):
    """상태 전이 결과"""

    new_state: SymbolState
    signal: Signal
    reason: str | None = None
    gc_date: datetime | None = None
    pullback_date: datetime | None = None


class GoldenCrossStateMachine:
    """
    골든크로스 상태 머신

    종목별 상태를 추적하고 시그널을 생성합니다.
    """

    def __init__(
        self,
        config: GoldenCrossConfigDTO | None = None,
    ):
        """
        Args:
            config: 골든크로스 전략 설정
        """
        self.config = config or GoldenCrossConfigDTO()
        self.stoch_config = self.config.stochastic_config
        self.risk_config = self.config.risk_config

    def process(
        self,
        current: IndicatorSnapshot,
        prev: IndicatorSnapshot,
        current_state: SymbolState,
        gc_date: datetime | None = None,
        pullback_date: datetime | None = None,
        entry_price: Decimal | None = None,
        entry_date: datetime | None = None,
        highest_price: Decimal | None = None,
        trailing_stop_activated: bool = False,
    ) -> StateTransition:
        """
        상태 머신 처리

        Args:
            current: 현재 지표 스냅샷
            prev: 이전 지표 스냅샷
            current_state: 현재 상태
            gc_date: 골든크로스 발생일
            pullback_date: 풀백 발생일
            entry_price: 진입가
            entry_date: 진입일
            highest_price: 포지션 진입 후 최고가 (트레일링 스탑용)
            trailing_stop_activated: 트레일링 스탑 활성화 여부

        Returns:
            StateTransition: 상태 전이 결과
        """
        # 1. WAITING_FOR_GC 상태
        if current_state == SymbolState.WAITING_FOR_GC:
            return self._process_waiting_for_gc(current, prev)

        # 2. WAITING_FOR_PULLBACK 상태
        elif current_state == SymbolState.WAITING_FOR_PULLBACK:
            return self._process_waiting_for_pullback(current, gc_date)

        # 3. READY_TO_BUY 상태
        elif current_state == SymbolState.READY_TO_BUY:
            return self._process_ready_to_buy(current, prev)

        # 4. IN_POSITION 상태
        elif current_state == SymbolState.IN_POSITION:
            return self._process_in_position(
                current,
                entry_price,
                entry_date,
                highest_price,
                trailing_stop_activated,
            )

        # 알 수 없는 상태 -> 초기화
        return StateTransition(
            new_state=SymbolState.WAITING_FOR_GC,
            signal=Signal.HOLD,
            reason=GoldenCrossTransitionReason.UNKNOWN_STATE_RESET.value,
        )

    def _process_waiting_for_gc(
        self, current: IndicatorSnapshot, prev: IndicatorSnapshot
    ) -> StateTransition:
        """
        골든크로스 대기 상태 처리

        조건: 전일 단기 MA <= 장기 MA AND 금일 단기 MA > 장기 MA
        """
        is_golden_cross = (
            prev.ma_short <= prev.ma_long and current.ma_short > current.ma_long
        )

        if is_golden_cross:
            return StateTransition(
                new_state=SymbolState.WAITING_FOR_PULLBACK,
                signal=Signal.HOLD,
                reason=GoldenCrossTransitionReason.GOLDEN_CROSS_DETECTED.value,
                gc_date=current.timestamp,
            )

        return StateTransition(
            new_state=SymbolState.WAITING_FOR_GC,
            signal=Signal.HOLD,
        )

    def _process_waiting_for_pullback(
        self, current: IndicatorSnapshot, gc_date: datetime | None
    ) -> StateTransition:
        """
        풀백 대기 상태 처리

        조건:
        - GC 무효화: 단기 MA < 장기 MA -> 초기화
        - 풀백 발생: Stoch K < oversold_threshold
        """
        # GC 무효화 체크
        if not current.is_gc_active:
            return StateTransition(
                new_state=SymbolState.WAITING_FOR_GC,
                signal=Signal.HOLD,
                reason=GoldenCrossTransitionReason.GC_INVALIDATED.value,
            )

        # 풀백 감지 (과매도)
        if current.stoch_k < self.stoch_config.oversold_threshold:
            return StateTransition(
                new_state=SymbolState.READY_TO_BUY,
                signal=Signal.HOLD,
                reason=GoldenCrossTransitionReason.PULLBACK_DETECTED.value,
                gc_date=gc_date,
                pullback_date=current.timestamp,
            )

        return StateTransition(
            new_state=SymbolState.WAITING_FOR_PULLBACK,
            signal=Signal.HOLD,
            gc_date=gc_date,
        )

    def _process_ready_to_buy(
        self,
        current: IndicatorSnapshot,
        prev: IndicatorSnapshot,
    ) -> StateTransition:
        """
        매수 준비 상태 처리

        조건:
        - GC 무효화: 단기 MA < 장기 MA -> 초기화
        - 매수 시그널: 스캔과 같은 풀백 회복 진입 계약 충족
        """
        # GC 무효화 체크
        if not current.is_gc_active:
            return StateTransition(
                new_state=SymbolState.WAITING_FOR_GC,
                signal=Signal.HOLD,
                reason=GoldenCrossTransitionReason.GC_INVALIDATED_DURING_READY.value,
            )

        # 잘못된 장기 MA로는 신뢰할 수 있는 갭을 계산할 수 없으므로 보수적으로 대기한다.
        if current.ma_long <= 0:
            return StateTransition(
                new_state=SymbolState.READY_TO_BUY,
                signal=Signal.HOLD,
            )

        ma_gap_ratio = float((current.ma_short - current.ma_long) / current.ma_long * 100)
        buy_entry_ready = GoldenCrossStrategyContract.is_buy_entry_ready(
            GoldenCrossScanContext(
                is_gc_active=current.is_gc_active,
                stoch_k=current.stoch_k,
                stoch_d=current.stoch_d,
                stoch_threshold=self.stoch_config.oversold_threshold,
                ma_gap_ratio=ma_gap_ratio,
                prev_stoch_k=prev.stoch_k,
                # READY_TO_BUY 자체가 풀백 발생을 보장한다. 초기화되거나 기존에
                # 저장된 상태에는 pullback_date가 없을 수 있다.
                recent_oversold=True,
                recovery_threshold=self.stoch_config.recovery_threshold,
                strong_recovery_threshold=self.stoch_config.strong_recovery_threshold,
                require_momentum_turn=self.stoch_config.require_momentum_turn,
            )
        )

        if buy_entry_ready:
            reason = (
                GoldenCrossTransitionReason.STOCH_STRONG_RECOVERY.value
                if current.stoch_k >= self.stoch_config.strong_recovery_threshold
                else GoldenCrossTransitionReason.STOCH_RECOVERY_CROSSOVER.value
            )
            return StateTransition(
                new_state=SymbolState.IN_POSITION,
                signal=Signal.BUY,
                reason=reason,
            )

        return StateTransition(
            new_state=SymbolState.READY_TO_BUY,
            signal=Signal.HOLD,
        )

    def _process_in_position(
        self,
        current: IndicatorSnapshot,
        entry_price: Decimal | None,
        entry_date: datetime | None,
        highest_price: Decimal | None = None,
        trailing_stop_activated: bool = False,
    ) -> StateTransition:
        """
        포지션 보유 상태 처리

        청산 조건:
        1. 데드크로스 (단기 MA < 장기 MA)
        2. 손절
        3. 익절
        4. 트레일링 스탑
        5. 최대 보유 기간 초과
        """
        # 1. 데드크로스 체크
        if not current.is_gc_active:
            return StateTransition(
                new_state=SymbolState.WAITING_FOR_GC,
                signal=Signal.SELL,
                reason=GoldenCrossRiskExitReason.DEAD_CROSS.value,
            )

        # 수익률 계산
        if entry_price and entry_price > 0:
            pnl_ratio = float((current.close - entry_price) / entry_price)

            # 2. 손절 체크
            if self.risk_config.use_stop_loss:
                if pnl_ratio <= self.risk_config.stop_loss_ratio:
                    return StateTransition(
                        new_state=SymbolState.WAITING_FOR_GC,
                        signal=Signal.SELL,
                        reason=GoldenCrossRiskExitReason.STOP_LOSS.value,
                    )

            # 3. 익절 체크
            if self.risk_config.use_take_profit:
                if pnl_ratio >= self.risk_config.take_profit_ratio:
                    return StateTransition(
                        new_state=SymbolState.WAITING_FOR_GC,
                        signal=Signal.SELL,
                        reason=GoldenCrossRiskExitReason.TAKE_PROFIT.value,
                    )

            # 4. 트레일링 스탑 체크
            if self.risk_config.use_trailing_stop and highest_price and highest_price > 0:
                is_trailing_active = (
                    trailing_stop_activated
                    or pnl_ratio >= self.risk_config.trailing_stop_activation
                )
                if is_trailing_active:
                    # 고점 대비 하락폭 체크
                    drawdown = float((highest_price - current.close) / highest_price)
                    # 발동 조건: 고점 대비 trailing_stop_distance (기본 7%) 이상 하락
                    if drawdown >= self.risk_config.trailing_stop_distance:
                        return StateTransition(
                            new_state=SymbolState.WAITING_FOR_GC,
                            signal=Signal.SELL,
                            reason=GoldenCrossRiskExitReason.TRAILING_STOP.value,
                        )

        # 5. 최대 보유 기간 체크
        if entry_date:
            days_held = (current.timestamp - entry_date).days
            if days_held >= self.risk_config.max_hold_days:
                return StateTransition(
                    new_state=SymbolState.WAITING_FOR_GC,
                    signal=Signal.SELL,
                    reason=GoldenCrossRiskExitReason.MAX_HOLD.value,
                )

        return StateTransition(
            new_state=SymbolState.IN_POSITION,
            signal=Signal.HOLD,
        )

    def get_initial_state(self, current: IndicatorSnapshot) -> SymbolState:
        """
        초기 상태 결정

        현재 지표 상태에 따라 적절한 초기 상태를 결정합니다.
        """
        # 이미 골든크로스 상태인 경우
        if current.is_gc_active:
            # 이미 과매도 상태
            if current.stoch_k < self.stoch_config.oversold_threshold:
                return SymbolState.READY_TO_BUY
            # 풀백 대기
            return SymbolState.WAITING_FOR_PULLBACK

        return SymbolState.WAITING_FOR_GC


