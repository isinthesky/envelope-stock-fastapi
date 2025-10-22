# -*- coding: utf-8 -*-
"""
Account Model - 계좌 정보 모델
"""

from decimal import Decimal

from sqlalchemy import BigInteger, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from src.adapters.database.connection import Base
from src.adapters.database.models.base import BaseModel


class AccountModel(Base, BaseModel):
    """계좌 정보 모델"""

    __tablename__ = "accounts"

    # ==================== Primary Key ====================
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # ==================== 계좌 기본 정보 ====================
    account_no: Mapped[str] = mapped_column(
        String(20), unique=True, nullable=False, index=True, comment="계좌번호"
    )

    account_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="계좌명"
    )

    product_code: Mapped[str] = mapped_column(
        String(10), nullable=False, comment="상품코드 (01: 종합, 03: 선물옵션)"
    )

    # ==================== 계좌 잔고 정보 ====================
    total_balance: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=0, comment="총 평가 금액"
    )

    cash_balance: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=0, comment="예수금 (현금)"
    )

    stock_balance: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=0, comment="주식 평가 금액"
    )

    available_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=0, comment="출금 가능 금액"
    )

    # ==================== 손익 정보 ====================
    total_profit_loss: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=0, comment="총 손익"
    )

    total_profit_loss_rate: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), nullable=False, default=0, comment="총 손익률 (%)"
    )

    realized_profit_loss: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=0, comment="실현 손익"
    )

    unrealized_profit_loss: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=0, comment="평가 손익"
    )

    # ==================== 거래 정보 ====================
    total_purchase_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=0, comment="총 매입 금액"
    )

    total_commission: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=0, comment="총 수수료"
    )

    total_tax: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=0, comment="총 세금"
    )

    # ==================== 포지션 정보 ====================
    position_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, comment="보유 종목 수"
    )

    # ==================== 환경 정보 ====================
    is_paper_trading: Mapped[bool] = mapped_column(
        nullable=False, default=False, comment="모의투자 여부"
    )

    # ==================== 메타데이터 ====================
    metadata_json: Mapped[str | None] = mapped_column(
        String(1000), nullable=True, comment="추가 메타데이터 (JSON)"
    )

    # ==================== Indexes ====================
    __table_args__ = (
        Index("ix_accounts_account_no", "account_no"),
        Index("ix_accounts_is_paper_trading", "is_paper_trading"),
    )

    # ==================== Properties ====================

    @property
    def profit_loss_rate(self) -> float:
        """손익률 (%)"""
        if self.total_purchase_amount == 0:
            return 0.0
        return float((self.total_profit_loss / self.total_purchase_amount) * 100)

    @property
    def asset_ratio(self) -> dict[str, float]:
        """자산 비율"""
        if self.total_balance == 0:
            return {"cash": 0.0, "stock": 0.0}
        return {
            "cash": float((self.cash_balance / self.total_balance) * 100),
            "stock": float((self.stock_balance / self.total_balance) * 100),
        }
