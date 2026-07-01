# -*- coding: utf-8 -*-
"""
Recommendation Domain DTO 테스트
"""

from datetime import datetime
from decimal import Decimal

from src.application.domain.recommendation.dto import (
    ReadinessLabel,
    RecommendationCandidateDTO,
    RecommendationCandidateListDTO,
    RecommendationScorecardDTO,
)


def test_recommendation_candidate_dto_holds_expected_fields() -> None:
    scorecard = RecommendationScorecardDTO(
        technical_score=90.0,
        fundamental_score=100.0,
        quant_score=90.0,
        final_score=94.0,
    )
    candidate = RecommendationCandidateDTO(
        symbol="005930",
        name="삼성전자",
        market="KOSPI",
        current_price=Decimal("70000"),
        technical_state="OPTIMAL_BUY",
        has_fundamental_evidence=True,
        scorecard=scorecard,
        readiness_label=ReadinessLabel.RESEARCH,
        missing_evidence=["news_review", "valuation_review"],
        blocked_actions=["auto_order"],
    )

    assert candidate.symbol == "005930"
    assert candidate.readiness_label == ReadinessLabel.RESEARCH
    assert "auto_order" in candidate.blocked_actions
    assert candidate.scorecard.final_score == 94.0


def test_recommendation_candidate_list_dto_holds_summary_fields() -> None:
    result = RecommendationCandidateListDTO(
        candidates=[],
        total_scanned=0,
        candidate_count=0,
        generated_at=datetime(2026, 7, 1, 9, 0, 0),
    )

    assert result.candidates == []
    assert result.candidate_count == 0
    assert result.total_scanned == 0
