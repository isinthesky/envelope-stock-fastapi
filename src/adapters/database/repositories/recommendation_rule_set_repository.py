# -*- coding: utf-8 -*-
"""
Recommendation Rule Set Repository - 추천 검색식 룰셋/검증 결과 데이터 접근 계층
"""

from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.database.models.recommendation_rule_set import (
    RecommendationRuleSetModel,
    RecommendationRuleValidationModel,
)
from src.adapters.database.repositories.base_repository import BaseRepository


class RecommendationRuleSetRepository(BaseRepository[RecommendationRuleSetModel]):
    """추천 검색식 룰셋 Repository"""

    def __init__(self, session: AsyncSession | None = None) -> None:
        super().__init__(RecommendationRuleSetModel, session)

    async def get_active_by_id(
        self, rule_set_id: int, session: AsyncSession | None = None
    ) -> RecommendationRuleSetModel | None:
        """active 상태인 룰셋만 조회 (스캔에서 사용할 룰셋 검증용)"""
        instance = await self.get_by_id(rule_set_id, session=session)
        if instance is None or instance.status != "active":
            return None
        return instance

    async def list_all(
        self,
        limit: int = 100,
        offset: int = 0,
        session: AsyncSession | None = None,
    ) -> Sequence[RecommendationRuleSetModel]:
        db = self._get_session(session)
        stmt = select(self.model).order_by(self.model.id).limit(limit).offset(offset)
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_latest_version_by_name(
        self, name: str, session: AsyncSession | None = None
    ) -> int | None:
        """동일 이름의 기존 룰셋 중 최대 버전. 없으면 None(신규 등록은 버전 1부터)."""
        db = self._get_session(session)
        stmt = select(func.max(self.model.version)).where(self.model.name == name)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()


class RecommendationRuleValidationRepository(BaseRepository[RecommendationRuleValidationModel]):
    """추천 룰셋 walk-forward 검증 결과 Repository"""

    def __init__(self, session: AsyncSession | None = None) -> None:
        super().__init__(RecommendationRuleValidationModel, session)

    async def get_latest_by_rule_set_id(
        self, rule_set_id: int, session: AsyncSession | None = None
    ) -> RecommendationRuleValidationModel | None:
        db = self._get_session(session)
        stmt = (
            select(self.model)
            .where(self.model.rule_set_id == rule_set_id)
            .order_by(self.model.id.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
