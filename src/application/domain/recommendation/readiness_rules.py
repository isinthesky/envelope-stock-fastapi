# -*- coding: utf-8 -*-
"""
Recommendation Readiness Rules

골든크로스 상태 + 가치주 스크리너 통과 여부만으로 scorecard와 readiness_label을
산출하는 순수 규칙 함수 모음. AI/DART/뉴스 연동 없음 (Phase 1 범위).

라벨 정의는 `.omo/analysis/tradingcodex-feature-patterns.md` 3.3~3.4절 참고.
"""

from src.application.domain.recommendation.dto import (
    ReadinessLabel,
    RecommendationScorecardDTO,
)

# gc_state -> 기술 점수 매핑 (0~100). 상태 우선순위는 BuyStrategyService의
# 정렬 기준(OPTIMAL_BUY > BUY_INTEREST > READY_TO_BUY > ...)과 동일하게 맞춘다.
_TECHNICAL_SCORE_BY_GC_STATE: dict[str, float] = {
    "OPTIMAL_BUY": 90.0,
    "BUY_INTEREST": 75.0,
    "READY_TO_BUY": 60.0,
    "WAITING_FOR_PULLBACK": 40.0,
    "GC_ACTIVE": 25.0,
    "NOT_GC": 0.0,
}

# RESEARCH로 승격 가능한 gc_state (재무 근거까지 있어야 함)
_RESEARCH_ELIGIBLE_STATES = {"OPTIMAL_BUY", "BUY_INTEREST"}

# 재무 근거 없이도 WATCH까지는 허용하는 gc_state
_WATCH_ELIGIBLE_STATES = {
    "OPTIMAL_BUY",
    "BUY_INTEREST",
    "READY_TO_BUY",
    "WAITING_FOR_PULLBACK",
    "GC_ACTIVE",
}

# Phase 1은 AI/실주문 연동이 없으므로 항상 차단
_ALWAYS_BLOCKED_ACTIONS = ("auto_order",)

# Phase 1에서 아직 수집하지 않는 증거 (Phase 3 AI evidence pack에서 채워짐)
_ALWAYS_MISSING_EVIDENCE = ("news_review", "valuation_review")


def compute_technical_score(gc_state: str) -> float:
    """gc_state를 0~100 기술 점수로 변환. 알 수 없는 상태는 0점."""
    return _TECHNICAL_SCORE_BY_GC_STATE.get(gc_state, 0.0)


def compute_scorecard(gc_state: str, has_fundamental_evidence: bool) -> RecommendationScorecardDTO:
    """
    기술 점수 + 재무 근거 존재 여부로 scorecard를 합성한다.

    fundamental_score는 가치주 스크리너 통과 시 100점, 미평가 시 None으로 둔다.
    스크리너 결과에 없다는 것이 "재무 상태가 나쁘다"는 뜻은 아니므로(단순 미평가일
    수 있음) 0점이 아니라 None으로 구분한다.
    """
    technical_score = compute_technical_score(gc_state)
    fundamental_score = 100.0 if has_fundamental_evidence else None

    if fundamental_score is None:
        final_score = technical_score
    else:
        final_score = round(technical_score * 0.6 + fundamental_score * 0.4, 1)

    return RecommendationScorecardDTO(
        technical_score=technical_score,
        fundamental_score=fundamental_score,
        quant_score=technical_score,
        final_score=final_score,
    )


def determine_readiness(
    gc_state: str, has_fundamental_evidence: bool
) -> tuple[ReadinessLabel, list[str], list[str]]:
    """
    readiness_label / missing_evidence / blocked_actions를 결정한다.

    Returns:
        (readiness_label, missing_evidence, blocked_actions)
    """
    missing_evidence: list[str] = []
    if not has_fundamental_evidence:
        missing_evidence.append("fundamental_review")
    missing_evidence.extend(_ALWAYS_MISSING_EVIDENCE)

    blocked_actions = list(_ALWAYS_BLOCKED_ACTIONS)

    if gc_state in _RESEARCH_ELIGIBLE_STATES and has_fundamental_evidence:
        label = ReadinessLabel.RESEARCH
    elif gc_state in _WATCH_ELIGIBLE_STATES:
        label = ReadinessLabel.WATCH
    else:
        label = ReadinessLabel.BLOCKED

    return label, missing_evidence, blocked_actions
