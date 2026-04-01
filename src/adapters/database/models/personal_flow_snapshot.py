# -*- coding: utf-8 -*-
"""Personal flow snapshot model - 종목 개인 수급 스냅샷"""

from sqlalchemy import BigInteger, DateTime, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from src.adapters.database.connection import Base
from src.adapters.database.models.base import BaseModel


class PersonalFlowSnapshotModel(Base, BaseModel):
    __tablename__ = "personal_flow_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="NAVER")
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    biz_date: Mapped[str] = mapped_column(String(8), nullable=False)
    individual_net_buy: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    close_price: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    trading_volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    fetched_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("source", "symbol", "biz_date", name="uq_personal_flow_snapshot"),
        Index("ix_personal_flow_symbol_date", "symbol", "biz_date"),
    )
