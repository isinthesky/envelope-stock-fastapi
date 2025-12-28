# -*- coding: utf-8 -*-
"""
Stock Universe Model - 종목 유니버스 모델

전략에서 사용할 종목 풀 관리
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import BigInteger, Boolean, DateTime, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.adapters.database.connection import Base
from src.adapters.database.models.base import BaseModel


class MarketType(str, Enum):
    """시장 구분"""

    KOSPI = "KOSPI"
    KOSDAQ = "KOSDAQ"


class StockUniverseModel(Base, BaseModel):
    """
    종목 유니버스 모델

    시가총액, 거래량 등 스크리닝 조건에 따라 선별된 종목 풀을 관리합니다.
    """

    __tablename__ = "stock_universe"

    # ==================== Primary Key ====================
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # ==================== 종목 기본 정보 ====================
    symbol: Mapped[str] = mapped_column(
        String(20), nullable=False, unique=True, index=True, comment="종목코드"
    )

    name: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="종목명"
    )

    market: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True, comment="시장 구분 (KOSPI/KOSDAQ)"
    )

    sector: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True, comment="섹터"
    )

    industry: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="산업"
    )

    # ==================== 시가총액 & 거래량 ====================
    market_cap: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 0), nullable=True, index=True, comment="시가총액 (원)"
    )

    avg_volume_20d: Mapped[Decimal | None] = mapped_column(
        Numeric(15, 0), nullable=True, index=True, comment="20일 평균 거래량"
    )

    avg_turnover_20d: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 0), nullable=True, comment="20일 평균 거래대금"
    )

    # ==================== 가격 정보 ====================
    current_price: Mapped[Decimal | None] = mapped_column(
        Numeric(15, 2), nullable=True, comment="현재가"
    )

    price_change_ratio: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4), nullable=True, comment="등락률"
    )

    week_52_high: Mapped[Decimal | None] = mapped_column(
        Numeric(15, 2), nullable=True, comment="52주 최고가"
    )

    week_52_low: Mapped[Decimal | None] = mapped_column(
        Numeric(15, 2), nullable=True, comment="52주 최저가"
    )

    # ==================== 스크리닝 상태 ====================
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True, comment="활성 여부"
    )

    is_tradable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, comment="거래 가능 여부"
    )

    is_excluded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="제외 여부 (수동)"
    )

    exclude_reason: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="제외 사유"
    )

    # ==================== 스크리닝 조건 ====================
    passed_market_cap: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, comment="시가총액 조건 통과"
    )

    passed_volume: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, comment="거래량 조건 통과"
    )

    passed_price_range: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, comment="가격대 조건 통과"
    )

    screening_score: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 2), nullable=True, comment="스크리닝 점수"
    )

    # ==================== 메타데이터 ====================
    metadata_json: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="추가 메타데이터 (JSON)"
    )

    # ==================== 타임스탬프 ====================
    data_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="데이터 갱신 시각"
    )

    screened_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="스크리닝 시각"
    )

    # ==================== Indexes ====================
    __table_args__ = (
        Index("ix_stock_universe_symbol", "symbol"),
        Index("ix_stock_universe_market", "market"),
        Index("ix_stock_universe_market_cap", "market_cap"),
        Index("ix_stock_universe_is_active", "is_active"),
        Index("ix_stock_universe_screening", "is_active", "is_tradable", "is_excluded"),
    )

    # ==================== Properties ====================

    @property
    def is_eligible(self) -> bool:
        """스크리닝 통과 여부"""
        return (
            self.is_active
            and self.is_tradable
            and not self.is_excluded
            and self.passed_market_cap is True
            and self.passed_volume is True
        )

    @property
    def market_cap_in_billion(self) -> float | None:
        """시가총액 (억원)"""
        if self.market_cap is None:
            return None
        return float(self.market_cap) / 100_000_000

    @property
    def from_52w_high_ratio(self) -> float | None:
        """52주 고점 대비 비율"""
        if self.current_price is None or self.week_52_high is None:
            return None
        if self.week_52_high == 0:
            return None
        return float(self.current_price / self.week_52_high)
