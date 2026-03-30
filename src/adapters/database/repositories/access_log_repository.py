# -*- coding: utf-8 -*-
"""
Access Log Repository - 접근 로그 데이터 접근 계층

세션 계약:
- 새 패턴: 생성자에서 session 받지 않고, 메서드 파라미터로 전달
- 기존 패턴: 하위 호환을 위해 생성자에서 session 받는 것도 지원
"""

from datetime import datetime
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.database.models.access_log import AccessLogModel
from src.adapters.database.repositories.base_repository import (
    BaseRepository,
    PaginationMixin,
)


class AccessLogRepository(BaseRepository[AccessLogModel], PaginationMixin):
    """
    접근 로그 Repository

    페이지 접근 로그를 저장하고 조회합니다.

    세션 계약:
    - 새 패턴: __init__에서 session 없이 생성, 메서드에서 session 파라미터로 전달
    - 기존 패턴: __init__에서 session 전달 (하위 호환)
    """

    def __init__(self, session: AsyncSession | None = None) -> None:
        super().__init__(AccessLogModel, session)

    async def get_recent_logs(
        self,
        limit: int = 100,
        offset: int = 0,
        path_filter: str | None = None,
        ip_filter: str | None = None,
        session: AsyncSession | None = None,
    ) -> Sequence[AccessLogModel]:
        """
        최근 접근 로그 조회

        Args:
            limit: 최대 조회 개수
            offset: 시작 위치
            path_filter: 경로 필터 (LIKE 검색)
            ip_filter: IP 필터 (정확히 일치)
            session: AsyncSession (새 패턴) 또는 None (기존 패턴)

        Returns:
            Sequence[AccessLogModel]: 접근 로그 목록
        """
        db = self._get_session(session)
        stmt = select(self.model).order_by(self.model.accessed_at.desc())

        if path_filter:
            stmt = stmt.where(self.model.path.like(f"%{path_filter}%"))

        if ip_filter:
            stmt = stmt.where(self.model.ip_address == ip_filter)

        stmt = stmt.limit(limit).offset(offset)
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_logs_by_date_range(
        self,
        start_date: datetime,
        end_date: datetime,
        limit: int = 1000,
        session: AsyncSession | None = None,
    ) -> Sequence[AccessLogModel]:
        """
        날짜 범위로 접근 로그 조회

        Args:
            start_date: 시작 날짜
            end_date: 종료 날짜
            limit: 최대 조회 개수
            session: AsyncSession

        Returns:
            Sequence[AccessLogModel]: 접근 로그 목록
        """
        db = self._get_session(session)
        stmt = (
            select(self.model)
            .where(
                self.model.accessed_at >= start_date,
                self.model.accessed_at <= end_date,
            )
            .order_by(self.model.accessed_at.desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_unique_ips(
        self,
        since: datetime | None = None,
        session: AsyncSession | None = None,
    ) -> list[str]:
        """
        고유 IP 목록 조회

        Args:
            since: 이 시각 이후의 로그만 조회
            session: AsyncSession

        Returns:
            list[str]: 고유 IP 목록
        """
        db = self._get_session(session)
        stmt = select(self.model.ip_address).distinct()

        if since:
            stmt = stmt.where(self.model.accessed_at >= since)

        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_path_stats(
        self,
        since: datetime | None = None,
        limit: int = 20,
        session: AsyncSession | None = None,
    ) -> list[dict]:
        """
        경로별 접근 통계 조회

        Args:
            since: 이 시각 이후의 로그만 조회
            limit: 최대 조회 개수
            session: AsyncSession

        Returns:
            list[dict]: [{"path": "/page/", "count": 100}, ...]
        """
        db = self._get_session(session)
        stmt = (
            select(self.model.path, func.count(self.model.id).label("count"))
            .group_by(self.model.path)
            .order_by(func.count(self.model.id).desc())
            .limit(limit)
        )

        if since:
            stmt = stmt.where(self.model.accessed_at >= since)

        result = await db.execute(stmt)
        return [{"path": row[0], "count": row[1]} for row in result.all()]

    async def get_ip_stats(
        self,
        since: datetime | None = None,
        limit: int = 20,
        session: AsyncSession | None = None,
    ) -> list[dict]:
        """
        IP별 접근 통계 조회

        Args:
            since: 이 시각 이후의 로그만 조회
            limit: 최대 조회 개수
            session: AsyncSession

        Returns:
            list[dict]: [{"ip": "1.2.3.4", "count": 100}, ...]
        """
        db = self._get_session(session)
        stmt = (
            select(self.model.ip_address, func.count(self.model.id).label("count"))
            .group_by(self.model.ip_address)
            .order_by(func.count(self.model.id).desc())
            .limit(limit)
        )

        if since:
            stmt = stmt.where(self.model.accessed_at >= since)

        result = await db.execute(stmt)
        return [{"ip": row[0], "count": row[1]} for row in result.all()]

    async def get_hourly_stats(
        self,
        since: datetime | None = None,
        session: AsyncSession | None = None,
    ) -> list[dict]:
        """
        시간대별 접근 통계 조회

        Args:
            since: 이 시각 이후의 로그만 조회
            session: AsyncSession

        Returns:
            list[dict]: [{"hour": "2024-01-14 10:00", "count": 50}, ...]
        """
        db = self._get_session(session)
        # PostgreSQL date_trunc 사용
        hour_trunc = func.date_trunc("hour", self.model.accessed_at)
        stmt = (
            select(hour_trunc.label("hour"), func.count(self.model.id).label("count"))
            .group_by(hour_trunc)
            .order_by(hour_trunc.desc())
            .limit(168)  # 최근 7일 (24 * 7)
        )

        if since:
            stmt = stmt.where(self.model.accessed_at >= since)

        result = await db.execute(stmt)
        return [{"hour": str(row[0]), "count": row[1]} for row in result.all()]

    async def get_total_count(
        self,
        since: datetime | None = None,
        session: AsyncSession | None = None,
    ) -> int:
        """
        전체 로그 개수 조회

        Args:
            since: 이 시각 이후의 로그만 조회
            session: AsyncSession

        Returns:
            int: 로그 개수
        """
        db = self._get_session(session)
        stmt = select(func.count(self.model.id))

        if since:
            stmt = stmt.where(self.model.accessed_at >= since)

        result = await db.execute(stmt)
        return result.scalar() or 0

    async def delete_old_logs(
        self,
        before: datetime,
        session: AsyncSession | None = None,
    ) -> int:
        """
        오래된 로그 삭제

        Args:
            before: 이 시각 이전의 로그 삭제
            session: AsyncSession

        Returns:
            int: 삭제된 로그 개수
        """
        db = self._get_session(session)
        stmt = select(self.model).where(self.model.accessed_at < before)
        result = await db.execute(stmt)
        logs = result.scalars().all()
        count = len(logs)

        for log in logs:
            await db.delete(log)

        return count
