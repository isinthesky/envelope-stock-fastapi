"""Recommendation domain"""

from .dto import (
    ReadinessLabel,
    RecommendationCandidateDTO,
    RecommendationCandidateListDTO,
    RecommendationRuleCandidateDTO,
    RecommendationRuleSetDTO,
    RecommendationScorecardDTO,
    RuleSetStatus,
)
from .recommendation_scan_service import RecommendationScanService

__all__ = [
    "ReadinessLabel",
    "RecommendationCandidateDTO",
    "RecommendationCandidateListDTO",
    "RecommendationRuleCandidateDTO",
    "RecommendationRuleSetDTO",
    "RecommendationScorecardDTO",
    "RuleSetStatus",
    "RecommendationScanService",
]
