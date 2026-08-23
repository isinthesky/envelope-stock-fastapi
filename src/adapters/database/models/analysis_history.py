# -*- coding: utf-8 -*-
"""
Analysis History Model - 분석 결과 이력 모델

매수/매도 전략 분석 결과를 저장하고 추적합니다.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import BigInteger, Boolean, DateTime, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.adapters.database.connection import Base
from src.adapters.database.models.base import BaseModel


class AnalysisType(str, Enum):
    """분석 유형"""

    BUY = "buy"  # 매수 분석 (골든크로스)
    SELL = "sell"  # 매도 분석


class AnalysisHistoryModel(Base, BaseModel):
    """
    분석 결과 이력 모델

    매수/매도 전략의 분석 결과를 저장하고 추적합니다.
    """

    __tablename__ = "analysis_history"

    # ==================== Primary Key ====================
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # ==================== 기본 정보 ====================
    analysis_type: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True, comment="분석 유형 (buy/sell)"
    )

    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True, comment="종목코드")

    name: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="종목명")

    # ==================== 가격 정보 ====================
    current_price: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, comment="현재가")

    # ==================== 공통 지표 ====================
    ma_short: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2), nullable=True, comment="단기 MA (40일)"
    )

    ma_long: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2), nullable=True, comment="장기 MA (160일)"
    )

    ma_gap_ratio: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4), nullable=True, comment="MA 갭 비율 (%)"
    )

    stoch_k: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4), nullable=True, comment="Stochastic K"
    )

    stoch_d: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4), nullable=True, comment="Stochastic D"
    )

    # ==================== 매수 분석용 (골든크로스) ====================
    gc_state: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
        comment="골든크로스 상태 (NOT_GC, GC_ACTIVE, WAITING_FOR_PULLBACK, READY_TO_BUY)",
    )

    is_gc_active: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, comment="골든크로스 활성 여부"
    )

    # ==================== 매도 분석용 ====================
    rsi: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True, comment="RSI (14일)")

    is_death_cross: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, comment="데드크로스 여부 (단기 MA < 장기 MA)"
    )

    is_stoch_overbought: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, comment="Stochastic 과매수 여부"
    )

    is_rsi_overbought: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, comment="RSI 과매수 여부"
    )

    sell_phase: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="매도 Phase (NONE, PHASE_1~5)"
    )

    sell_stage: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="최종 매도 Stage"
    )

    sell_ratio_min: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4), nullable=True, comment="최종 최소 권장 매도 비율"
    )

    sell_ratio_max: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4), nullable=True, comment="최종 최대 권장 매도 비율"
    )

    sell_reasons: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="매도 근거 (JSON array)"
    )

    # ==================== 메타데이터 ====================
    analyzed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="분석 시각"
    )

    entry_price: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2), nullable=True, comment="진입가 (수익률 계산용)"
    )

    highest_price: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2), nullable=True, comment="보유 중 최고가 (고점 대비 손절 계산용)"
    )

    note: Mapped[str | None] = mapped_column(Text, nullable=True, comment="사용자 메모")

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, comment="활성 추적 여부"
    )

    candle_count: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="분석에 사용된 캔들 수"
    )

    # ==================== Indexes ====================
    __table_args__ = (
        Index("ix_analysis_history_type_symbol", "analysis_type", "symbol"),
        Index("ix_analysis_history_analyzed_at", "analyzed_at"),
        Index("ix_analysis_history_is_active", "is_active"),
        Index("ix_analysis_history_type_active", "analysis_type", "is_active"),
    )

    # ==================== Properties ====================

    @property
    def is_buy_analysis(self) -> bool:
        """매수 분석 여부"""
        return self.analysis_type == AnalysisType.BUY.value

    @property
    def is_sell_analysis(self) -> bool:
        """매도 분석 여부"""
        return self.analysis_type == AnalysisType.SELL.value
