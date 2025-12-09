# -*- coding: utf-8 -*-
"""
OHLCV Model - 캔들 데이터 캐시 모델
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    DateTime,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.adapters.database.connection import Base
from src.adapters.database.models.base import BaseModel


class OHLCVModel(Base, BaseModel):
    """OHLCV 캔들 데이터 캐시 모델"""

    __tablename__ = "ohlcv_cache"

    # ==================== Primary Key ====================
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # ==================== 종목 정보 ====================
    symbol: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True, comment="종목코드"
    )

    # ==================== 시간 정보 ====================
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True, comment="캔들 시각"
    )

    interval: Mapped[str] = mapped_column(
        String(10), nullable=False, default="1d", comment="시간 간격 (1d, 1w, 1m)"
    )

    # ==================== OHLCV 데이터 ====================
    open: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, comment="시가"
    )

    high: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, comment="고가"
    )

    low: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, comment="저가"
    )

    close: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, comment="종가"
    )

    volume: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="거래량"
    )

    # ==================== 추가 정보 ====================
    adjusted: Mapped[bool] = mapped_column(
        nullable=False, default=False, comment="수정주가 여부"
    )

    source: Mapped[str] = mapped_column(
        String(20), nullable=False, default="kis", comment="데이터 출처 (kis, yfinance 등)"
    )

    # ==================== Constraints ====================
    __table_args__ = (
        # 종목 + 시각 + 간격 조합은 유일
        UniqueConstraint("symbol", "timestamp", "interval", name="uq_ohlcv_symbol_timestamp_interval"),
        # 조회 성능 향상을 위한 복합 인덱스
        Index("ix_ohlcv_symbol_timestamp", "symbol", "timestamp"),
        Index("ix_ohlcv_symbol_interval_timestamp", "symbol", "interval", "timestamp"),
    )

    # ==================== Properties ====================

    @property
    def price_range(self) -> Decimal:
        """가격 범위 (고가 - 저가)"""
        return self.high - self.low

    @property
    def is_bullish(self) -> bool:
        """상승 캔들 여부"""
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        """하락 캔들 여부"""
        return self.close < self.open

    @property
    def body_size(self) -> Decimal:
        """캔들 몸통 크기"""
        return abs(self.close - self.open)

    @property
    def upper_shadow(self) -> Decimal:
        """위꼬리 크기"""
        return self.high - max(self.open, self.close)

    @property
    def lower_shadow(self) -> Decimal:
        """아래꼬리 크기"""
        return min(self.open, self.close) - self.low

    def to_candle_dict(self) -> dict:
        """CandleDTO 호환 딕셔너리 변환"""
        return {
            "timestamp": self.timestamp,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }
