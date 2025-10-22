# -*- coding: utf-8 -*-
"""
Order Model - 주문 정보 모델
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
)
from sqlalchemy.orm import Mapped, mapped_column

from src.adapters.database.connection import Base
from src.adapters.database.models.base import BaseModel


class OrderType(str, Enum):
    """주문 유형"""

    BUY = "buy"  # 매수
    SELL = "sell"  # 매도


class OrderStatus(str, Enum):
    """주문 상태"""

    PENDING = "pending"  # 대기
    SUBMITTED = "submitted"  # 제출
    PARTIALLY_FILLED = "partially_filled"  # 부분 체결
    FILLED = "filled"  # 전체 체결
    CANCELED = "canceled"  # 취소
    REJECTED = "rejected"  # 거부
    FAILED = "failed"  # 실패


class PriceType(str, Enum):
    """가격 유형"""

    MARKET = "market"  # 시장가
    LIMIT = "limit"  # 지정가
    STOP = "stop"  # 조건부 지정가


class OrderModel(Base, BaseModel):
    """주문 모델"""

    __tablename__ = "orders"

    # ==================== Primary Key ====================
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # ==================== 주문 기본 정보 ====================
    order_id: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True, comment="주문 ID (KIS API)"
    )

    account_no: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True, comment="계좌번호"
    )

    symbol: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True, comment="종목코드"
    )

    symbol_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="종목명"
    )

    # ==================== 주문 상세 ====================
    order_type: Mapped[str] = mapped_column(
        String(10), nullable=False, comment="주문 유형 (buy/sell)"
    )

    price_type: Mapped[str] = mapped_column(
        String(10), nullable=False, comment="가격 유형 (market/limit/stop)"
    )

    order_price: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, comment="주문 가격"
    )

    order_quantity: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="주문 수량")

    filled_quantity: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, comment="체결 수량"
    )

    filled_avg_price: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=0, comment="체결 평균가"
    )

    # ==================== 주문 상태 ====================
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=OrderStatus.PENDING.value,
        index=True,
        comment="주문 상태",
    )

    status_message: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="상태 메시지"
    )

    # ==================== 타임스탬프 ====================
    order_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="주문 시각"
    )

    filled_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="체결 시각"
    )

    # ==================== 수수료 및 세금 ====================
    commission: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=0, comment="수수료"
    )

    tax: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=0, comment="세금"
    )

    # ==================== 전략 연동 ====================
    strategy_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, index=True, comment="전략 ID (연동)"
    )

    # ==================== 메타데이터 ====================
    metadata_json: Mapped[str | None] = mapped_column(
        String(1000), nullable=True, comment="추가 메타데이터 (JSON)"
    )

    # ==================== Indexes ====================
    __table_args__ = (
        Index("ix_orders_account_status", "account_no", "status"),
        Index("ix_orders_symbol_status", "symbol", "status"),
        Index("ix_orders_order_time", "order_time"),
        Index("ix_orders_strategy_id", "strategy_id"),
    )

    # ==================== Properties ====================

    @property
    def is_filled(self) -> bool:
        """전체 체결 여부"""
        return self.status == OrderStatus.FILLED.value

    @property
    def is_partially_filled(self) -> bool:
        """부분 체결 여부"""
        return self.status == OrderStatus.PARTIALLY_FILLED.value

    @property
    def remaining_quantity(self) -> int:
        """미체결 수량"""
        return self.order_quantity - self.filled_quantity

    @property
    def fill_rate(self) -> float:
        """체결률 (%)"""
        if self.order_quantity == 0:
            return 0.0
        return (self.filled_quantity / self.order_quantity) * 100

    @property
    def total_amount(self) -> Decimal:
        """총 거래 금액 (체결 금액)"""
        return self.filled_avg_price * Decimal(self.filled_quantity)

    @property
    def total_cost(self) -> Decimal:
        """총 비용 (거래 금액 + 수수료 + 세금)"""
        return self.total_amount + self.commission + self.tax
