# -*- coding: utf-8 -*-
"""
Recommendation Rule Set Model - 추천 검색식 룰셋/walk-forward 검증 결과 모델
"""

from datetime import date

from sqlalchemy import BigInteger, Boolean, Date, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.adapters.database.connection import Base
from src.adapters.database.models.base import BaseModel


class RecommendationRuleSetModel(Base, BaseModel):
    """추천 검색식 룰셋 (후보 정의 + 마지막 검증 결과 요약)"""

    __tablename__ = "recommendation_rule_sets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True, comment="룰셋 이름")
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, comment="버전")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", comment="draft/active/archived"
    )
    candidates_json: Mapped[str] = mapped_column(
        Text, nullable=False, comment="RecommendationRuleCandidateDTO 리스트 JSON"
    )
    frozen_hash: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="검증 후 선택된 후보의 frozen_hash"
    )

    __table_args__ = (
        Index("ix_recommendation_rule_sets_name_version", "name", "version"),
        Index("ix_recommendation_rule_sets_status", "status"),
    )


class RecommendationRuleValidationModel(Base, BaseModel):
    """추천 룰셋의 walk-forward 검증 실행 결과"""

    __tablename__ = "recommendation_rule_validations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    rule_set_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("recommendation_rule_sets.id", ondelete="CASCADE"),
        nullable=False,
    )
    benchmark: Mapped[str] = mapped_column(String(20), nullable=False, comment="벤치마크 심볼")
    selection_metric: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="cagr/excess_return/sharpe"
    )

    train_start: Mapped[date] = mapped_column(Date, nullable=False)
    train_end: Mapped[date] = mapped_column(Date, nullable=False)
    test_start: Mapped[date] = mapped_column(Date, nullable=False)
    test_end: Mapped[date] = mapped_column(Date, nullable=False)

    selected_candidate_id: Mapped[str] = mapped_column(String(100), nullable=False)
    selected_candidate_hash: Mapped[str] = mapped_column(String(32), nullable=False)
    data_snooping_warning: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    train_metrics_json: Mapped[str] = mapped_column(
        Text, nullable=False, comment="선택 후보 train WindowMetrics JSON"
    )
    test_metrics_json: Mapped[str] = mapped_column(
        Text, nullable=False, comment="선택 후보 test WindowMetrics JSON"
    )
    report_markdown: Mapped[str] = mapped_column(
        Text, nullable=False, comment="WalkForwardValidationResult.to_markdown() 리포트"
    )

    __table_args__ = (Index("ix_recommendation_rule_validations_rule_set_id", "rule_set_id"),)
