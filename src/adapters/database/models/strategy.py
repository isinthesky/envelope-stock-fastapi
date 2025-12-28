# -*- coding: utf-8 -*-
"""
Strategy Model - 자동매매 전략 모델
"""

from datetime import datetime
from enum import Enum

from sqlalchemy import BigInteger, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.adapters.database.connection import Base
from src.adapters.database.models.base import BaseModel, SoftDeleteMixin


class StrategyStatus(str, Enum):
    """전략 상태"""

    ACTIVE = "active"  # 활성
    PAUSED = "paused"  # 일시정지
    STOPPED = "stopped"  # 중지
    COMPLETED = "completed"  # 완료


class StrategyType(str, Enum):
    """전략 유형"""

    MOMENTUM = "momentum"  # 모멘텀
    MEAN_REVERSION = "mean_reversion"  # 평균 회귀
    BREAKOUT = "breakout"  # 돌파
    GRID = "grid"  # 그리드
    GOLDEN_CROSS = "golden_cross"  # 골든크로스
    CUSTOM = "custom"  # 커스텀


class StrategyModel(Base, BaseModel, SoftDeleteMixin):
    """자동매매 전략 모델"""

    __tablename__ = "strategies"

    # ==================== Primary Key ====================
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # ==================== 전략 기본 정보 ====================
    name: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True, comment="전략명"
    )

    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="전략 설명")

    strategy_type: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="전략 유형"
    )

    # ==================== 계좌 및 종목 ====================
    account_no: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True, comment="계좌번호"
    )

    symbols: Mapped[str] = mapped_column(
        String(500), nullable=False, comment="대상 종목 (쉼표 구분)"
    )

    # ==================== 전략 상태 ====================
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=StrategyStatus.PAUSED.value,
        index=True,
        comment="전략 상태",
    )

    # ==================== 전략 설정 (JSON) ====================
    config_json: Mapped[str] = mapped_column(
        Text, nullable=False, comment="전략 설정 (JSON)"
    )

    # ==================== 실행 통계 ====================
    total_executions: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, comment="총 실행 횟수"
    )

    successful_executions: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, comment="성공 실행 횟수"
    )

    failed_executions: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, comment="실패 실행 횟수"
    )

    # ==================== 타임스탬프 ====================
    last_executed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="마지막 실행 시각"
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="시작 시각"
    )

    stopped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="중지 시각"
    )

    # ==================== 메타데이터 ====================
    metadata_json: Mapped[str | None] = mapped_column(
        String(1000), nullable=True, comment="추가 메타데이터 (JSON)"
    )

    # ==================== Indexes ====================
    __table_args__ = (
        Index("ix_strategies_account_status", "account_no", "status"),
        Index("ix_strategies_status", "status"),
        Index("ix_strategies_name", "name"),
    )

    # ==================== Properties ====================

    @property
    def is_active(self) -> bool:
        """활성 상태 여부"""
        return self.status == StrategyStatus.ACTIVE.value

    @property
    def success_rate(self) -> float:
        """성공률 (%)"""
        if self.total_executions == 0:
            return 0.0
        return (self.successful_executions / self.total_executions) * 100

    @property
    def symbol_list(self) -> list[str]:
        """종목 리스트"""
        return [s.strip() for s in self.symbols.split(",") if s.strip()]
