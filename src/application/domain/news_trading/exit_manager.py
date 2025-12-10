# -*- coding: utf-8 -*-
"""
Exit Manager - 청산 관리 모듈

Phase 2 (cross_pollination.md) 기반:
- 분할 익절 (+5%에서 50%, +8%에서 잔여 전량)
- 모멘텀 기반 동적 익절
- 손절 (-7%)
- 시간 청산 (10:40)
"""

from dataclasses import dataclass, field
from datetime import datetime, time, date
from decimal import Decimal
from typing import Any

from src.application.domain.news_trading.dto import (
    ExitReason,
    ExitConditionConfigDTO,
    MomentumSignal,
    TradingSignalDTO,
    TradingStatus,
)
from src.application.domain.news_trading.momentum_detector import MomentumDetector


@dataclass
class PositionState:
    """포지션 상태"""
    symbol: str
    name: str

    # 진입 정보
    entry_time: datetime
    entry_price: Decimal
    total_quantity: int
    remaining_quantity: int

    # 청산 정보
    first_exit_done: bool = False
    first_exit_time: datetime | None = None
    first_exit_price: Decimal | None = None
    first_exit_quantity: int | None = None
    first_exit_reason: ExitReason | None = None

    # 손익 추적
    realized_profit: Decimal = Decimal("0")
    unrealized_profit: Decimal = Decimal("0")
    peak_price: Decimal | None = None  # 고점 (Trailing Stop용)

    # 상태
    status: TradingStatus = TradingStatus.POSITION_OPEN

    # 뉴스/모멘텀 메타데이터
    news_score: float = 0.0
    event_types: list[str] = field(default_factory=list)

    @property
    def current_profit_rate(self) -> float:
        """현재 수익률"""
        if self.entry_price <= 0:
            return 0.0
        return float((self.unrealized_profit) / (self.entry_price * self.total_quantity)) * 100

    @property
    def holding_duration_minutes(self) -> int:
        """보유 시간 (분)"""
        return int((datetime.now() - self.entry_time).total_seconds() / 60)


class ExitManager:
    """
    청산 관리자

    주요 기능:
    1. 분할 익절 (1차: +5% → 50%, 2차: +8% → 전량)
    2. 모멘텀 기반 동적 익절
    3. 손절 (-7%)
    4. 시간 청산 (10:40)
    """

    def __init__(
        self,
        config: ExitConditionConfigDTO | None = None,
        momentum_detector: MomentumDetector | None = None,
    ):
        """
        Args:
            config: 청산 조건 설정 (None이면 기본값 사용)
            momentum_detector: 모멘텀 감지기 (None이면 새로 생성)
        """
        self.config = config or ExitConditionConfigDTO()
        self.momentum_detector = momentum_detector or MomentumDetector(
            config=self.config.momentum_exit
        )
        self.positions: dict[str, PositionState] = {}

    def open_position(
        self,
        symbol: str,
        name: str,
        entry_time: datetime,
        entry_price: Decimal,
        quantity: int,
        news_score: float = 0.0,
        event_types: list[str] | None = None,
    ) -> PositionState:
        """
        포지션 오픈

        Args:
            symbol: 종목코드
            name: 종목명
            entry_time: 진입 시각
            entry_price: 진입 가격
            quantity: 수량
            news_score: 뉴스 스코어
            event_types: 관련 이벤트 유형

        Returns:
            생성된 포지션 상태
        """
        position = PositionState(
            symbol=symbol,
            name=name,
            entry_time=entry_time,
            entry_price=entry_price,
            total_quantity=quantity,
            remaining_quantity=quantity,
            peak_price=entry_price,
            news_score=news_score,
            event_types=event_types or [],
        )
        self.positions[symbol] = position
        return position

    def close_position(self, symbol: str) -> PositionState | None:
        """포지션 정리 (완전 청산)"""
        return self.positions.pop(symbol, None)

    def get_position(self, symbol: str) -> PositionState | None:
        """포지션 조회"""
        return self.positions.get(symbol)

    def update_price(
        self,
        symbol: str,
        current_price: Decimal,
        current_time: datetime,
    ) -> None:
        """
        현재가 업데이트

        Args:
            symbol: 종목코드
            current_price: 현재가
            current_time: 현재 시각
        """
        position = self.positions.get(symbol)
        if not position:
            return

        # 평가 손익 계산
        position.unrealized_profit = (
            (current_price - position.entry_price) * position.remaining_quantity
        )

        # 고점 업데이트 (Trailing Stop용)
        if position.peak_price is None or current_price > position.peak_price:
            position.peak_price = current_price

    def check_exit_conditions(
        self,
        symbol: str,
        current_price: Decimal,
        current_time: datetime,
    ) -> TradingSignalDTO | None:
        """
        청산 조건 체크

        우선순위:
        1. 손절 (-7%)
        2. 시간 청산 (10:40)
        3. 1차 익절 (+5%)
        4. 2차 익절 (+8%)
        5. 모멘텀 약화 익절

        Args:
            symbol: 종목코드
            current_price: 현재가
            current_time: 현재 시각

        Returns:
            청산 신호 (조건 충족 시) 또는 None
        """
        position = self.positions.get(symbol)
        if not position or position.status == TradingStatus.CLOSED:
            return None

        # 현재가 업데이트
        self.update_price(symbol, current_price, current_time)

        # 수익률 계산
        profit_rate = float(
            (current_price - position.entry_price) / position.entry_price
        )

        staged_config = self.config.staged_profit_taking
        momentum_config = self.config.momentum_exit

        # 1. 손절 체크 (-7%)
        if profit_rate <= self.config.stop_loss_rate:
            return self._create_sell_signal(
                position=position,
                current_price=current_price,
                current_time=current_time,
                quantity=position.remaining_quantity,
                exit_reason=ExitReason.STOP_LOSS,
                is_full_exit=True,
            )

        # 2. 시간 청산 체크 (10:40)
        if self._is_force_exit_time(current_time):
            return self._create_sell_signal(
                position=position,
                current_price=current_price,
                current_time=current_time,
                quantity=position.remaining_quantity,
                exit_reason=ExitReason.TIME_EXIT,
                is_full_exit=True,
            )

        # 3. 1차 익절 체크 (+5%, 50% 물량)
        if (
            not position.first_exit_done
            and profit_rate >= staged_config.first_take_profit_rate
        ):
            exit_quantity = int(
                position.total_quantity * staged_config.first_take_profit_ratio
            )
            return self._create_sell_signal(
                position=position,
                current_price=current_price,
                current_time=current_time,
                quantity=exit_quantity,
                exit_reason=ExitReason.FIRST_PROFIT_TAKING,
                is_full_exit=False,
            )

        # 4. 2차 익절 체크 (+8%, 잔여 전량)
        if (
            position.first_exit_done
            and profit_rate >= staged_config.second_take_profit_rate
        ):
            return self._create_sell_signal(
                position=position,
                current_price=current_price,
                current_time=current_time,
                quantity=position.remaining_quantity,
                exit_reason=ExitReason.SECOND_PROFIT_TAKING,
                is_full_exit=True,
            )

        # 5. 모멘텀 약화 익절 체크 (1차 익절 후에만)
        if position.first_exit_done and momentum_config.require_first_profit:
            if self.momentum_detector.is_momentum_weak(symbol):
                signals = self.momentum_detector.get_or_create_state(symbol).active_signals
                return self._create_sell_signal(
                    position=position,
                    current_price=current_price,
                    current_time=current_time,
                    quantity=position.remaining_quantity,
                    exit_reason=ExitReason.MOMENTUM_EXIT,
                    is_full_exit=True,
                    momentum_signals=signals,
                )

        return None

    def _create_sell_signal(
        self,
        position: PositionState,
        current_price: Decimal,
        current_time: datetime,
        quantity: int,
        exit_reason: ExitReason,
        is_full_exit: bool,
        momentum_signals: list[MomentumSignal] | None = None,
    ) -> TradingSignalDTO:
        """청산 신호 생성"""
        return TradingSignalDTO(
            signal_time=current_time,
            symbol=position.symbol,
            signal_type="sell",
            reason=f"{exit_reason.value}: {position.name}",
            price=current_price,
            quantity=quantity,
            exit_reason=exit_reason,
            momentum_signals=momentum_signals or [],
            momentum_weight_sum=(
                self.momentum_detector.get_or_create_state(position.symbol).signal_weight_sum
                if momentum_signals
                else 0
            ),
        )

    def execute_partial_exit(
        self,
        symbol: str,
        exit_price: Decimal,
        exit_quantity: int,
        exit_time: datetime,
        exit_reason: ExitReason,
    ) -> Decimal:
        """
        부분 청산 실행 (1차 익절)

        Args:
            symbol: 종목코드
            exit_price: 청산 가격
            exit_quantity: 청산 수량
            exit_time: 청산 시각
            exit_reason: 청산 사유

        Returns:
            실현 손익
        """
        position = self.positions.get(symbol)
        if not position:
            return Decimal("0")

        # 실현 손익 계산
        realized = (exit_price - position.entry_price) * exit_quantity
        position.realized_profit += realized

        # 잔여 수량 업데이트
        position.remaining_quantity -= exit_quantity

        # 1차 익절 기록
        if not position.first_exit_done:
            position.first_exit_done = True
            position.first_exit_time = exit_time
            position.first_exit_price = exit_price
            position.first_exit_quantity = exit_quantity
            position.first_exit_reason = exit_reason
            position.status = TradingStatus.PARTIALLY_CLOSED

        return realized

    def execute_full_exit(
        self,
        symbol: str,
        exit_price: Decimal,
        exit_time: datetime,
        exit_reason: ExitReason,
    ) -> Decimal:
        """
        완전 청산 실행

        Args:
            symbol: 종목코드
            exit_price: 청산 가격
            exit_time: 청산 시각
            exit_reason: 청산 사유

        Returns:
            실현 손익
        """
        position = self.positions.get(symbol)
        if not position:
            return Decimal("0")

        # 잔여 물량 청산
        realized = (exit_price - position.entry_price) * position.remaining_quantity
        position.realized_profit += realized
        position.remaining_quantity = 0
        position.status = TradingStatus.CLOSED

        return realized

    def _is_force_exit_time(self, current_time: datetime) -> bool:
        """강제 청산 시간 도달 여부"""
        current_time_only = current_time.time()
        return current_time_only >= self.config.force_exit_time

    def get_position_summary(self, symbol: str) -> dict[str, Any] | None:
        """포지션 요약 정보"""
        position = self.positions.get(symbol)
        if not position:
            return None

        return {
            "symbol": position.symbol,
            "name": position.name,
            "entry_time": position.entry_time.isoformat(),
            "entry_price": float(position.entry_price),
            "total_quantity": position.total_quantity,
            "remaining_quantity": position.remaining_quantity,
            "first_exit_done": position.first_exit_done,
            "realized_profit": float(position.realized_profit),
            "unrealized_profit": float(position.unrealized_profit),
            "current_profit_rate": position.current_profit_rate,
            "holding_duration_minutes": position.holding_duration_minutes,
            "status": position.status.value,
            "news_score": position.news_score,
        }

    def get_all_positions(self) -> list[dict[str, Any]]:
        """모든 포지션 요약"""
        return [
            self.get_position_summary(symbol)
            for symbol in self.positions
            if self.get_position_summary(symbol) is not None
        ]


class BacktestExitManager:
    """
    백테스트용 청산 관리자

    분봉 데이터 기반 청산 조건 체크 (단순화된 버전)
    """

    def __init__(self, config: ExitConditionConfigDTO | None = None):
        self.config = config or ExitConditionConfigDTO()

    def check_exit_from_bar(
        self,
        entry_price: float,
        current_bar: dict[str, Any],
        first_exit_done: bool = False,
        bar_time: datetime | None = None,
    ) -> tuple[ExitReason | None, float]:
        """
        분봉 데이터에서 청산 조건 체크

        Args:
            entry_price: 진입 가격
            current_bar: 현재 분봉 데이터 (high, low, close)
            first_exit_done: 1차 익절 완료 여부
            bar_time: 분봉 시각 (시간 청산 체크용)

        Returns:
            (청산 사유, 청산 가격) 또는 (None, 0)
        """
        high = current_bar.get("high", 0)
        low = current_bar.get("low", 0)
        close = current_bar.get("close", 0)

        if entry_price <= 0:
            return None, 0

        staged_config = self.config.staged_profit_taking

        # 1. 손절 체크 (Low 기준)
        low_rate = (low - entry_price) / entry_price
        if low_rate <= self.config.stop_loss_rate:
            # 손절가 계산
            stop_price = entry_price * (1 + self.config.stop_loss_rate)
            return ExitReason.STOP_LOSS, stop_price

        # 2. 시간 청산 체크
        if bar_time and bar_time.time() >= self.config.force_exit_time:
            return ExitReason.TIME_EXIT, close

        # 3. 1차 익절 체크 (High 기준)
        high_rate = (high - entry_price) / entry_price
        if not first_exit_done and high_rate >= staged_config.first_take_profit_rate:
            # 1차 익절가 계산
            take_profit_price = entry_price * (1 + staged_config.first_take_profit_rate)
            return ExitReason.FIRST_PROFIT_TAKING, take_profit_price

        # 4. 2차 익절 체크 (High 기준)
        if first_exit_done and high_rate >= staged_config.second_take_profit_rate:
            take_profit_price = entry_price * (1 + staged_config.second_take_profit_rate)
            return ExitReason.SECOND_PROFIT_TAKING, take_profit_price

        return None, 0

    def calculate_profit(
        self,
        entry_price: float,
        exit_price: float,
        quantity: int,
        commission_rate: float = 0.00015,
        tax_rate: float = 0.0023,
    ) -> dict[str, float]:
        """
        손익 계산

        Args:
            entry_price: 진입 가격
            exit_price: 청산 가격
            quantity: 수량
            commission_rate: 수수료율
            tax_rate: 세금율 (매도 시)

        Returns:
            손익 정보 딕셔너리
        """
        entry_amount = entry_price * quantity
        exit_amount = exit_price * quantity

        # 수수료 (매수 + 매도)
        buy_commission = entry_amount * commission_rate
        sell_commission = exit_amount * commission_rate

        # 세금 (매도만)
        sell_tax = exit_amount * tax_rate

        # 총 비용
        total_cost = buy_commission + sell_commission + sell_tax

        # 손익
        gross_profit = exit_amount - entry_amount
        net_profit = gross_profit - total_cost
        profit_rate = (net_profit / entry_amount) * 100 if entry_amount > 0 else 0

        return {
            "entry_amount": entry_amount,
            "exit_amount": exit_amount,
            "gross_profit": gross_profit,
            "commission": buy_commission + sell_commission,
            "tax": sell_tax,
            "total_cost": total_cost,
            "net_profit": net_profit,
            "profit_rate": profit_rate,
        }
