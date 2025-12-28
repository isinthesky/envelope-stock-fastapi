# -*- coding: utf-8 -*-
"""
Strategy Symbol State Model - 종목별 전략 상태 모델

골든크로스 전략의 종목별 상태 머신 관리
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import (
    BigInteger,
    DateTime,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.adapters.database.connection import Base
from src.adapters.database.models.base import BaseModel


class SymbolState(str, Enum):
    """종목 상태 (상태 머신)"""

    WAITING_FOR_GC = "WAITING_FOR_GC"  # 골든크로스 대기
    WAITING_FOR_PULLBACK = "WAITING_FOR_PULLBACK"  # 풀백 대기
    READY_TO_BUY = "READY_TO_BUY"  # 매수 준비
    IN_POSITION = "IN_POSITION"  # 포지션 보유 중


class StrategySymbolStateModel(Base, BaseModel):
    """
    전략별 종목 상태 모델

    골든크로스 전략의 종목별 상태 머신을 관리합니다.
    """

    __tablename__ = "strategy_symbol_states"

    # ==================== Primary Key ====================
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # ==================== Foreign Keys ====================
    strategy_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, index=True, comment="전략 ID"
    )

    # ==================== 종목 정보 ====================
    symbol: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True, comment="종목코드"
    )

    # ==================== 상태 머신 ====================
    state: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=SymbolState.WAITING_FOR_GC.value,
        comment="현재 상태",
    )

    # ==================== 골든크로스 관련 ====================
    gc_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="골든크로스 발생일"
    )

    pullback_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="풀백 발생일"
    )

    # ==================== 포지션 관련 ====================
    entry_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="진입일"
    )

    entry_price: Mapped[Decimal | None] = mapped_column(
        Numeric(15, 2), nullable=True, comment="진입가"
    )

    quantity: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="보유 수량"
    )

    # ==================== 지표 스냅샷 ====================
    last_ma_short: Mapped[Decimal | None] = mapped_column(
        Numeric(15, 2), nullable=True, comment="최근 단기 MA"
    )

    last_ma_long: Mapped[Decimal | None] = mapped_column(
        Numeric(15, 2), nullable=True, comment="최근 장기 MA"
    )

    last_stoch_k: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 2), nullable=True, comment="최근 Stochastic K"
    )

    last_stoch_d: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 2), nullable=True, comment="최근 Stochastic D"
    )

    last_close: Mapped[Decimal | None] = mapped_column(
        Numeric(15, 2), nullable=True, comment="최근 종가"
    )

    # ==================== 메타데이터 ====================
    metadata_json: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="추가 메타데이터 (JSON)"
    )

    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="마지막 체크 시각"
    )

    # ==================== Indexes & Constraints ====================
    __table_args__ = (
        UniqueConstraint("strategy_id", "symbol", name="uq_strategy_symbol"),
        Index("ix_strategy_symbol_states_strategy_id", "strategy_id"),
        Index("ix_strategy_symbol_states_symbol", "symbol"),
        Index("ix_strategy_symbol_states_state", "state"),
    )

    # ==================== Properties ====================

    @property
    def is_in_position(self) -> bool:
        """포지션 보유 여부"""
        return self.state == SymbolState.IN_POSITION.value

    @property
    def is_waiting_for_gc(self) -> bool:
        """골든크로스 대기 상태 여부"""
        return self.state == SymbolState.WAITING_FOR_GC.value

    @property
    def is_ready_to_buy(self) -> bool:
        """매수 준비 상태 여부"""
        return self.state == SymbolState.READY_TO_BUY.value

    @property
    def days_since_entry(self) -> int | None:
        """진입 후 경과일"""
        if self.entry_date is None:
            return None
        return (datetime.now() - self.entry_date).days

    @property
    def unrealized_pnl_ratio(self) -> float | None:
        """미실현 수익률"""
        if self.entry_price is None or self.last_close is None:
            return None
        if self.entry_price == 0:
            return None
        return float((self.last_close - self.entry_price) / self.entry_price)
