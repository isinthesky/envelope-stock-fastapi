# -*- coding: utf-8 -*-
"""
Analysis History Repository - 분석 이력 데이터 접근 계층
"""

from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.database.models.analysis_history import AnalysisHistoryModel
from src.adapters.database.repositories.base_repository import (
    BaseRepository,
    PaginationMixin,
)


class AnalysisHistoryRepository(BaseRepository[AnalysisHistoryModel], PaginationMixin):
    """
    분석 이력 Repository

    매수/매도 분석 결과 이력을 저장하고 조회합니다.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(AnalysisHistoryModel, session)

    async def get_by_type(
        self,
        analysis_type: str,
        is_active: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[AnalysisHistoryModel]:
        """
        분석 유형별 이력 조회

        Args:
            analysis_type: 분석 유형 (buy/sell)
            is_active: 활성 추적 여부 필터 (None이면 필터 없음)
            limit: 최대 조회 개수
            offset: 시작 위치

        Returns:
            Sequence[AnalysisHistoryModel]: 분석 이력 목록
        """
        stmt = select(self.model).where(
            self.model.analysis_type == analysis_type
        ).order_by(self.model.analyzed_at.desc())

        if is_active is not None:
            stmt = stmt.where(self.model.is_active == is_active)

        stmt = stmt.limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_active_symbols(self, analysis_type: str) -> list[str]:
        """
        활성 추적 중인 종목 코드 목록 조회

        Args:
            analysis_type: 분석 유형 (buy/sell)

        Returns:
            list[str]: 활성 추적 중인 종목 코드 목록
        """
        stmt = select(self.model.symbol).where(
            self.model.analysis_type == analysis_type,
            self.model.is_active == True,  # noqa: E712
        ).distinct()
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_active_symbols_with_names(
        self, analysis_type: str
    ) -> list[dict[str, str | None]]:
        """
        활성 추적 중인 종목 코드 및 종목명 조회

        Args:
            analysis_type: 분석 유형 (buy/sell)

        Returns:
            list[dict]: [{"symbol": "005930", "name": "삼성전자"}, ...]
        """
        stmt = select(self.model.symbol, self.model.name).where(
            self.model.analysis_type == analysis_type,
            self.model.is_active == True,  # noqa: E712
        ).distinct()
        result = await self.session.execute(stmt)
        return [{"symbol": row[0], "name": row[1]} for row in result.all()]

    async def get_by_symbol(
        self,
        symbol: str,
        analysis_type: str | None = None,
        limit: int = 10,
    ) -> Sequence[AnalysisHistoryModel]:
        """
        종목별 분석 이력 조회

        Args:
            symbol: 종목코드
            analysis_type: 분석 유형 (None이면 전체)
            limit: 최대 조회 개수

        Returns:
            Sequence[AnalysisHistoryModel]: 분석 이력 목록
        """
        stmt = select(self.model).where(
            self.model.symbol == symbol
        ).order_by(self.model.analyzed_at.desc())

        if analysis_type is not None:
            stmt = stmt.where(self.model.analysis_type == analysis_type)

        stmt = stmt.limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_latest_by_symbol(
        self,
        symbol: str,
        analysis_type: str,
    ) -> AnalysisHistoryModel | None:
        """
        종목의 최신 분석 이력 조회

        Args:
            symbol: 종목코드
            analysis_type: 분석 유형

        Returns:
            AnalysisHistoryModel | None: 최신 분석 이력 또는 None
        """
        stmt = select(self.model).where(
            self.model.symbol == symbol,
            self.model.analysis_type == analysis_type,
        ).order_by(self.model.analyzed_at.desc()).limit(1)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def set_active(self, id: int, is_active: bool) -> AnalysisHistoryModel | None:
        """
        활성 추적 상태 변경

        Args:
            id: 분석 이력 ID
            is_active: 활성 추적 여부

        Returns:
            AnalysisHistoryModel | None: 업데이트된 모델 또는 None
        """
        return await self.update_by_id(id, is_active=is_active)

    async def count_by_type(self, analysis_type: str, is_active: bool | None = None) -> int:
        """
        분석 유형별 이력 개수 조회

        Args:
            analysis_type: 분석 유형 (buy/sell)
            is_active: 활성 추적 여부 필터 (None이면 필터 없음)

        Returns:
            int: 분석 이력 개수
        """
        if is_active is not None:
            return await self.count(analysis_type=analysis_type, is_active=is_active)
        return await self.count(analysis_type=analysis_type)
