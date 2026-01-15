# -*- coding: utf-8 -*-
"""
Analysis History Repository - 분석 이력 데이터 접근 계층

세션 계약 (2026-01-14 업데이트):
- 새 패턴: 생성자에서 session 받지 않고, 메서드 파라미터로 전달
- 기존 패턴: 하위 호환을 위해 생성자에서 session 받는 것도 지원
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

    세션 계약:
    - 새 패턴: __init__에서 session 없이 생성, 메서드에서 session 파라미터로 전달
    - 기존 패턴: __init__에서 session 전달 (하위 호환)
    """

    def __init__(self, session: AsyncSession | None = None) -> None:
        super().__init__(AnalysisHistoryModel, session)

    async def get_by_type(
        self,
        analysis_type: str,
        is_active: bool | None = None,
        limit: int = 100,
        offset: int = 0,
        session: AsyncSession | None = None,
    ) -> Sequence[AnalysisHistoryModel]:
        """
        분석 유형별 이력 조회

        Args:
            analysis_type: 분석 유형 (buy/sell)
            is_active: 활성 추적 여부 필터 (None이면 필터 없음)
            limit: 최대 조회 개수
            offset: 시작 위치
            session: AsyncSession (새 패턴) 또는 None (기존 패턴)

        Returns:
            Sequence[AnalysisHistoryModel]: 분석 이력 목록
        """
        db = self._get_session(session)
        stmt = select(self.model).where(
            self.model.analysis_type == analysis_type
        ).order_by(self.model.analyzed_at.desc())

        if is_active is not None:
            stmt = stmt.where(self.model.is_active == is_active)

        stmt = stmt.limit(limit).offset(offset)
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_active_symbols(
        self, analysis_type: str, session: AsyncSession | None = None
    ) -> list[str]:
        """
        활성 추적 중인 종목 코드 목록 조회

        Args:
            analysis_type: 분석 유형 (buy/sell)
            session: AsyncSession (새 패턴) 또는 None (기존 패턴)

        Returns:
            list[str]: 활성 추적 중인 종목 코드 목록
        """
        db = self._get_session(session)
        stmt = select(self.model.symbol).where(
            self.model.analysis_type == analysis_type,
            self.model.is_active == True,  # noqa: E712
        ).distinct()
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_active_symbols_with_names(
        self, analysis_type: str, session: AsyncSession | None = None
    ) -> list[dict[str, str | None]]:
        """
        활성 추적 중인 종목 코드 및 종목명 조회

        Args:
            analysis_type: 분석 유형 (buy/sell)
            session: AsyncSession (새 패턴) 또는 None (기존 패턴)

        Returns:
            list[dict]: [{"symbol": "005930", "name": "삼성전자"}, ...]
        """
        db = self._get_session(session)
        stmt = select(self.model.symbol, self.model.name).where(
            self.model.analysis_type == analysis_type,
            self.model.is_active == True,  # noqa: E712
        ).distinct()
        result = await db.execute(stmt)
        return [{"symbol": row[0], "name": row[1]} for row in result.all()]

    async def get_by_symbol(
        self,
        symbol: str,
        analysis_type: str | None = None,
        limit: int = 10,
        session: AsyncSession | None = None,
    ) -> Sequence[AnalysisHistoryModel]:
        """
        종목별 분석 이력 조회

        Args:
            symbol: 종목코드
            analysis_type: 분석 유형 (None이면 전체)
            limit: 최대 조회 개수
            session: AsyncSession (새 패턴) 또는 None (기존 패턴)

        Returns:
            Sequence[AnalysisHistoryModel]: 분석 이력 목록
        """
        db = self._get_session(session)
        stmt = select(self.model).where(
            self.model.symbol == symbol
        ).order_by(self.model.analyzed_at.desc())

        if analysis_type is not None:
            stmt = stmt.where(self.model.analysis_type == analysis_type)

        stmt = stmt.limit(limit)
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_latest_by_symbol(
        self,
        symbol: str,
        analysis_type: str,
        session: AsyncSession | None = None,
    ) -> AnalysisHistoryModel | None:
        """
        종목의 최신 분석 이력 조회

        Args:
            symbol: 종목코드
            analysis_type: 분석 유형
            session: AsyncSession (새 패턴) 또는 None (기존 패턴)

        Returns:
            AnalysisHistoryModel | None: 최신 분석 이력 또는 None
        """
        db = self._get_session(session)
        stmt = select(self.model).where(
            self.model.symbol == symbol,
            self.model.analysis_type == analysis_type,
        ).order_by(self.model.analyzed_at.desc()).limit(1)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def set_active(
        self, id: int, is_active: bool, session: AsyncSession | None = None
    ) -> AnalysisHistoryModel | None:
        """
        활성 추적 상태 변경

        Args:
            id: 분석 이력 ID
            is_active: 활성 추적 여부
            session: AsyncSession (새 패턴) 또는 None (기존 패턴)

        Returns:
            AnalysisHistoryModel | None: 업데이트된 모델 또는 None
        """
        return await self.update_by_id(id, session=session, is_active=is_active)

    async def count_by_type(
        self,
        analysis_type: str,
        is_active: bool | None = None,
        session: AsyncSession | None = None,
    ) -> int:
        """
        분석 유형별 이력 개수 조회

        Args:
            analysis_type: 분석 유형 (buy/sell)
            is_active: 활성 추적 여부 필터 (None이면 필터 없음)
            session: AsyncSession (새 패턴) 또는 None (기존 패턴)

        Returns:
            int: 분석 이력 개수
        """
        if is_active is not None:
            return await self.count(
                session=session, analysis_type=analysis_type, is_active=is_active
            )
        return await self.count(session=session, analysis_type=analysis_type)
