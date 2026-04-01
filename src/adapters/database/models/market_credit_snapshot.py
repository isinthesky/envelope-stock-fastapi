# -*- coding: utf-8 -*-
"""Market credit snapshot model - 시장 신용공여 잔고 스냅샷"""

from sqlalchemy import BigInteger, DateTime, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from src.adapters.database.connection import Base
from src.adapters.database.models.base import BaseModel


class MarketCreditSnapshotModel(Base, BaseModel):
    __tablename__ = "market_credit_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="KOFIA")
    market_label: Mapped[str] = mapped_column(String(20), nullable=False)
    biz_date: Mapped[str] = mapped_column(String(8), nullable=False, comment="YYYYMMDD")
    trading_volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    balance_million: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    short_balance_million: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    fetched_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("source", "market_label", "biz_date", name="uq_market_credit_snapshot"),
        Index("ix_market_credit_market_date", "market_label", "biz_date"),
    )
