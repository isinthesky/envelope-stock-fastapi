# -*- coding: utf-8 -*-
"""
Strategy Signal Model - 전략 시그널 모델

전략에서 발생한 매수/매도 시그널 이력 관리
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import BigInteger, DateTime, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.adapters.database.connection import Base
from src.adapters.database.models.base import BaseModel


class SignalType(str, Enum):
    """시그널 유형"""

    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class SignalStatus(str, Enum):
    """시그널 상태"""

    PENDING = "pending"  # 대기 중
    EXECUTED = "executed"  # 실행됨
    CANCELLED = "cancelled"  # 취소됨
    FAILED = "failed"  # 실패
    SKIPPED = "skipped"  # 건너뜀 (SafetyGuard 등)


class ExitReason(str, Enum):
    """청산 사유"""

    DEAD_CROSS = "dead_cross"  # 데드크로스
    STOP_LOSS = "stop_loss"  # 손절
    TAKE_PROFIT = "take_profit"  # 익절
    TRAILING_STOP = "trailing_stop"  # 트레일링 스탑
    MAX_HOLD_DAYS = "max_hold_days"  # 최대 보유 기간 초과
    MANUAL = "manual"  # 수동 청산


class StrategySignalModel(Base, BaseModel):
    """
    전략 시그널 모델

    전략에서 발생한 모든 매수/매도 시그널을 기록합니다.
    """

    __tablename__ = "strategy_signals"

    # ==================== Primary Key ====================
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # ==================== Foreign Keys ====================
    strategy_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, index=True, comment="전략 ID"
    )

    # ==================== 시그널 정보 ====================
    symbol: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True, comment="종목코드"
    )

    signal_type: Mapped[str] = mapped_column(
        String(10), nullable=False, index=True, comment="시그널 유형 (buy/sell/hold)"
    )

    signal_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=SignalStatus.PENDING.value,
        index=True,
        comment="시그널 상태",
    )

    # ==================== 가격 정보 ====================
    signal_price: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, comment="시그널 발생 시점 가격"
    )

    target_quantity: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="목표 수량"
    )

    executed_price: Mapped[Decimal | None] = mapped_column(
        Numeric(15, 2), nullable=True, comment="체결 가격"
    )

    executed_quantity: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="체결 수량"
    )

    # ==================== 청산 관련 ====================
    exit_reason: Mapped[str | None] = mapped_column(
        String(30), nullable=True, comment="청산 사유"
    )

    realized_pnl: Mapped[Decimal | None] = mapped_column(
        Numeric(15, 2), nullable=True, comment="실현 손익"
    )

    realized_pnl_ratio: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4), nullable=True, comment="실현 수익률"
    )

    # ==================== 지표 스냅샷 ====================
    ma_short: Mapped[Decimal | None] = mapped_column(
        Numeric(15, 2), nullable=True, comment="단기 MA"
    )

    ma_long: Mapped[Decimal | None] = mapped_column(
        Numeric(15, 2), nullable=True, comment="장기 MA"
    )

    stoch_k: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 2), nullable=True, comment="Stochastic K"
    )

    stoch_d: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 2), nullable=True, comment="Stochastic D"
    )

    # ==================== 상태 전이 ====================
    prev_state: Mapped[str | None] = mapped_column(
        String(30), nullable=True, comment="이전 상태"
    )

    new_state: Mapped[str | None] = mapped_column(
        String(30), nullable=True, comment="새 상태"
    )

    # ==================== 주문 연동 ====================
    order_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="연동된 주문 ID"
    )

    order_no: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="주문번호"
    )

    # ==================== 메타데이터 ====================
    note: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="비고"
    )

    metadata_json: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="추가 메타데이터 (JSON)"
    )

    # ==================== 타임스탬프 ====================
    signal_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="시그널 발생 시각"
    )

    executed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="체결 시각"
    )

    # ==================== Indexes ====================
    __table_args__ = (
        Index("ix_strategy_signals_strategy_id", "strategy_id"),
        Index("ix_strategy_signals_symbol", "symbol"),
        Index("ix_strategy_signals_signal_type", "signal_type"),
        Index("ix_strategy_signals_signal_at", "signal_at"),
        Index("ix_strategy_signals_strategy_symbol", "strategy_id", "symbol"),
    )

    # ==================== Properties ====================

    @property
    def is_buy(self) -> bool:
        """매수 시그널 여부"""
        return self.signal_type == SignalType.BUY.value

    @property
    def is_sell(self) -> bool:
        """매도 시그널 여부"""
        return self.signal_type == SignalType.SELL.value

    @property
    def is_executed(self) -> bool:
        """체결 여부"""
        return self.signal_status == SignalStatus.EXECUTED.value

    @property
    def is_profitable(self) -> bool | None:
        """수익 여부"""
        if self.realized_pnl is None:
            return None
        return self.realized_pnl > 0
