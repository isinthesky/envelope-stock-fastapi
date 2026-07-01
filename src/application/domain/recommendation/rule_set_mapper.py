# -*- coding: utf-8 -*-
"""
RecommendationRuleSetDTO <-> RecommendationRuleSetModel 변환 헬퍼

candidates(list[RecommendationRuleCandidateDTO])를 JSON으로 직렬화/역직렬화한다.
strategy_service.py가 config_json을 다루는 것과 동일한 패턴이다.
"""

import json

from src.adapters.database.models.recommendation_rule_set import RecommendationRuleSetModel
from src.application.domain.recommendation.dto import (
    RecommendationRuleCandidateDTO,
    RecommendationRuleSetDTO,
    RuleSetStatus,
)


def candidates_to_json(candidates: list[RecommendationRuleCandidateDTO]) -> str:
    return json.dumps(
        [candidate.model_dump(mode="json") for candidate in candidates], sort_keys=True
    )


def rule_set_from_model(model: RecommendationRuleSetModel) -> RecommendationRuleSetDTO:
    candidates_data = json.loads(model.candidates_json)
    return RecommendationRuleSetDTO(
        rule_id=str(model.id),
        name=model.name,
        version=model.version,
        status=RuleSetStatus(model.status),
        candidates=[
            RecommendationRuleCandidateDTO.model_validate(item) for item in candidates_data
        ],
        frozen_hash=model.frozen_hash,
    )
