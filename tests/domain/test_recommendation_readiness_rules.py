# -*- coding: utf-8 -*-
"""
Recommendation Readiness Rules 테스트
"""

from src.application.domain.recommendation.dto import ReadinessLabel
from src.application.domain.recommendation.readiness_rules import (
    compute_scorecard,
    determine_readiness,
)


def test_optimal_buy_with_fundamental_evidence_is_research_ready() -> None:
    label, missing_evidence, blocked_actions = determine_readiness(
        "OPTIMAL_BUY", has_fundamental_evidence=True
    )

    assert label == ReadinessLabel.RESEARCH
    assert "fundamental_review" not in missing_evidence
    assert "auto_order" in blocked_actions


def test_optimal_buy_without_fundamental_evidence_stays_watch_and_not_decision_ready() -> None:
    label, missing_evidence, blocked_actions = determine_readiness(
        "OPTIMAL_BUY", has_fundamental_evidence=False
    )

    assert label == ReadinessLabel.WATCH
    assert label != ReadinessLabel.DECISION_READY
    assert "fundamental_review" in missing_evidence
    assert "auto_order" in blocked_actions


def test_ready_to_buy_without_fundamental_evidence_is_watch_not_research() -> None:
    label, _, _ = determine_readiness("READY_TO_BUY", has_fundamental_evidence=False)

    assert label == ReadinessLabel.WATCH


def test_not_gc_is_blocked() -> None:
    label, _, _ = determine_readiness("NOT_GC", has_fundamental_evidence=True)

    assert label == ReadinessLabel.BLOCKED


def test_scorecard_uses_technical_only_when_fundamental_missing() -> None:
    scorecard = compute_scorecard("BUY_INTEREST", has_fundamental_evidence=False)

    assert scorecard.fundamental_score is None
    assert scorecard.final_score == scorecard.technical_score == scorecard.quant_score


def test_scorecard_blends_technical_and_fundamental_when_both_present() -> None:
    scorecard = compute_scorecard("OPTIMAL_BUY", has_fundamental_evidence=True)

    assert scorecard.fundamental_score == 100.0
    assert scorecard.technical_score == 90.0
    assert scorecard.final_score == round(90.0 * 0.6 + 100.0 * 0.4, 1)
