# -*- coding: utf-8 -*-
"""
RecommendationRuleSet DTO 테스트

frozen_hash가 backtest/validation.py의 CandidateRule.frozen_hash()에
위임되어 동일 rules -> 동일 hash, 다른 rules -> 다른 hash가 되는지 검증한다.
"""

from src.application.domain.backtest.validation import CandidateRule, WindowMetrics
from src.application.domain.recommendation.dto import (
    RecommendationRuleCandidateDTO,
    RecommendationRuleSetDTO,
    RuleSetStatus,
    compute_rule_frozen_hash,
)

_RULES_A = {"short_period": 55, "long_period": 165, "stoch_oversold": 30.0}
_RULES_B = {"short_period": 20, "long_period": 60, "stoch_oversold": 25.0}


def test_same_rules_produce_same_frozen_hash() -> None:
    candidate_1 = RecommendationRuleCandidateDTO(
        candidate_id="c1", name="baseline", rules=dict(_RULES_A)
    )
    candidate_2 = RecommendationRuleCandidateDTO(
        candidate_id="c1", name="baseline", rules=dict(_RULES_A)
    )

    assert candidate_1.frozen_hash == candidate_2.frozen_hash


def test_different_rules_produce_different_frozen_hash() -> None:
    candidate_1 = RecommendationRuleCandidateDTO(candidate_id="c1", name="baseline", rules=_RULES_A)
    candidate_2 = RecommendationRuleCandidateDTO(candidate_id="c1", name="baseline", rules=_RULES_B)

    assert candidate_1.frozen_hash != candidate_2.frozen_hash


def test_compute_rule_frozen_hash_matches_candidate_rule_frozen_hash() -> None:
    """compute_rule_frozen_hash가 CandidateRule.frozen_hash()와 동일한 값을 내야
    한다(같은 sha256/정렬 규칙을 위임하고 있다는 것을 보증)."""
    zero_metrics = WindowMetrics(cagr=0.0, benchmark_cagr=0.0, mdd=0.0, sharpe=0.0, turnover=0.0)
    reference = CandidateRule(
        candidate_id="c1",
        name="baseline",
        rules=_RULES_A,
        train_metrics=zero_metrics,
        test_metrics=zero_metrics,
    )

    assert compute_rule_frozen_hash("c1", "baseline", _RULES_A) == reference.frozen_hash()


def test_rule_set_dto_defaults_to_draft_status_and_no_frozen_hash() -> None:
    rule_set = RecommendationRuleSetDTO(
        rule_id="rs-1",
        name="golden-cross-swing",
        candidates=[
            RecommendationRuleCandidateDTO(candidate_id="c1", name="baseline", rules=_RULES_A)
        ],
    )

    assert rule_set.status == RuleSetStatus.DRAFT
    assert rule_set.version == 1
    assert rule_set.frozen_hash is None
