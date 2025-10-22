# -*- coding: utf-8 -*-
"""
Position Model - 보유 포지션 모델
"""

from decimal import Decimal

from sqlalchemy import BigInteger, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from src.adapters.database.connection import Base
from src.adapters.database.models.base import BaseModel


class PositionModel(Base, BaseModel):
    """보유 포지션 모델"""

    __tablename__ = "positions"

    # ==================== Primary Key ====================
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # ==================== 계좌 및 종목 정보 ====================
    account_no: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True, comment="계좌번호"
    )

    symbol: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True, comment="종목코드"
    )

    symbol_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="종목명"
    )

    # ==================== 보유 수량 ====================
    quantity: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="보유 수량")

    available_quantity: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, comment="매도 가능 수량"
    )

    # ==================== 가격 정보 ====================
    avg_purchase_price: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, comment="평균 매입가"
    )

    current_price: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=0, comment="현재가"
    )

    # ==================== 평가 정보 ====================
    purchase_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, comment="매입 금액"
    )

    evaluated_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=0, comment="평가 금액"
    )

    profit_loss: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=0, comment="평가 손익"
    )

    profit_loss_rate: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), nullable=False, default=0, comment="평가 손익률 (%)"
    )

    # ==================== 메타데이터 ====================
    metadata_json: Mapped[str | None] = mapped_column(
        String(1000), nullable=True, comment="추가 메타데이터 (JSON)"
    )

    # ==================== Indexes ====================
    __table_args__ = (
        Index("ix_positions_account_symbol", "account_no", "symbol", unique=True),
        Index("ix_positions_account_no", "account_no"),
        Index("ix_positions_symbol", "symbol"),
    )

    # ==================== Properties ====================

    @property
    def locked_quantity(self) -> int:
        """주문 중 수량 (보유 - 매도가능)"""
        return self.quantity - self.available_quantity

    @property
    def profit_loss_amount(self) -> Decimal:
        """손익 금액"""
        return self.evaluated_amount - self.purchase_amount

    @property
    def profit_loss_percentage(self) -> float:
        """손익률 (%)"""
        if self.purchase_amount == 0:
            return 0.0
        return float((self.profit_loss_amount / self.purchase_amount) * 100)

    @property
    def weight_ratio(self) -> float:
        """보유 비중 (계좌 총액 대비)"""
        # Note: 계좌 총액은 외부에서 계산 필요
        return 0.0
