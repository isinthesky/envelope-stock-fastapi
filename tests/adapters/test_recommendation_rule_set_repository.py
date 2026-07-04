# -*- coding: utf-8 -*-
"""
RecommendationRuleSetRepository / RecommendationRuleValidationRepository 테스트

실제 DB(로컬 docker postgres)에 대해 create/조회를 검증하고, 각 테스트는
세션을 커밋하지 않고 롤백해 데이터를 남기지 않는다.
"""

from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.database.connection import AsyncSessionLocal, engine
from src.adapters.database.repositories.recommendation_rule_set_repository import (
    RecommendationRuleSetRepository,
    RecommendationRuleValidationRepository,
)
from src.application.domain.recommendation.dto import RecommendationRuleCandidateDTO
from src.application.domain.recommendation.rule_set_mapper import candidates_to_json

# 실제 저장 형태(RecommendationRuleCandidateDTO 리스트의 JSON)를 그대로 재사용한다 -
# "{}" 같은 임의 문자열은 rule_set_from_model()이 실패하는 값이라 계약을 흐린다.
_SAMPLE_CANDIDATES_JSON = candidates_to_json(
    [RecommendationRuleCandidateDTO(candidate_id="c1", name="baseline", rules={"short_period": 55})]
)


@pytest.fixture
async def session():
    """
    pytest-asyncio는 테스트마다 새 이벤트 루프를 만든다(asyncio_mode=auto,
    function-scoped). 전역 엔진의 커넥션 풀이 이전 루프에 바인딩된 채로 남으면
    "attached to a different loop" 오류가 나므로, 테스트가 끝날 때마다 엔진을
    dispose해 다음 테스트가 새 루프에서 새 커넥션을 맺도록 한다.
    """
    async with AsyncSessionLocal() as db:
        try:
            await db.execute(text("SELECT 1"))
        except (ConnectionRefusedError, OSError, OperationalError) as exc:
            pytest.skip(f"local docker postgres is unavailable: {exc}")
        yield db
        await db.rollback()
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_and_fetch_rule_set_round_trips_candidates_json_and_frozen_hash(
    session: AsyncSession,
) -> None:
    repo = RecommendationRuleSetRepository()
    created = await repo.create(
        session=session,
        name="golden-cross-swing",
        version=1,
        status="draft",
        candidates_json=_SAMPLE_CANDIDATES_JSON,
        frozen_hash=None,
    )

    fetched = await repo.get_by_id(created.id, session=session)

    assert fetched is not None
    assert fetched.candidates_json == _SAMPLE_CANDIDATES_JSON
    assert fetched.frozen_hash is None
    assert fetched.status == "draft"


@pytest.mark.asyncio
async def test_get_active_by_id_returns_none_for_draft_rule_set(session: AsyncSession) -> None:
    repo = RecommendationRuleSetRepository()
    created = await repo.create(
        session=session,
        name="rs-draft",
        version=1,
        status="draft",
        candidates_json=_SAMPLE_CANDIDATES_JSON,
    )

    active = await repo.get_active_by_id(created.id, session=session)

    assert active is None


@pytest.mark.asyncio
async def test_get_active_by_id_returns_instance_for_active_rule_set(
    session: AsyncSession,
) -> None:
    repo = RecommendationRuleSetRepository()
    created = await repo.create(
        session=session,
        name="rs-active",
        version=1,
        status="active",
        candidates_json=_SAMPLE_CANDIDATES_JSON,
        frozen_hash="abc123",
    )

    active = await repo.get_active_by_id(created.id, session=session)

    assert active is not None
    assert active.id == created.id
    assert active.frozen_hash == "abc123"


@pytest.mark.asyncio
async def test_validation_repository_returns_latest_by_rule_set_id(
    session: AsyncSession,
) -> None:
    rule_set_repo = RecommendationRuleSetRepository()
    validation_repo = RecommendationRuleValidationRepository()

    rule_set = await rule_set_repo.create(
        session=session,
        name="rs-validated",
        version=1,
        status="active",
        candidates_json=_SAMPLE_CANDIDATES_JSON,
    )

    def _validation_kwargs(selected_candidate_id: str) -> dict:
        return dict(
            session=session,
            rule_set_id=rule_set.id,
            benchmark="0001",
            selection_metric="cagr",
            train_start=date(2024, 1, 1),
            train_end=date(2024, 6, 30),
            test_start=date(2024, 7, 1),
            test_end=date(2024, 12, 31),
            selected_candidate_id=selected_candidate_id,
            selected_candidate_hash="hash-" + selected_candidate_id,
            data_snooping_warning=True,
            train_metrics_json="{}",
            test_metrics_json="{}",
            report_markdown="# report",
        )

    await validation_repo.create(**_validation_kwargs("c1"))
    latest = await validation_repo.create(**_validation_kwargs("c2"))

    fetched_latest = await validation_repo.get_latest_by_rule_set_id(rule_set.id, session=session)

    assert fetched_latest is not None
    assert fetched_latest.id == latest.id
    assert fetched_latest.selected_candidate_id == "c2"
    assert fetched_latest.data_snooping_warning is True


@pytest.mark.asyncio
async def test_get_latest_by_rule_set_id_returns_none_when_no_validation_exists(
    session: AsyncSession,
) -> None:
    rule_set_repo = RecommendationRuleSetRepository()
    validation_repo = RecommendationRuleValidationRepository()

    rule_set = await rule_set_repo.create(
        session=session,
        name="rs-unvalidated",
        version=1,
        status="draft",
        candidates_json=_SAMPLE_CANDIDATES_JSON,
    )

    fetched = await validation_repo.get_latest_by_rule_set_id(rule_set.id, session=session)

    assert fetched is None
