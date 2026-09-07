# -*- coding: utf-8 -*-
"""
Access Log Service - 접근 로그 조회/통계/정리 유즈케이스

세션 계약 (RecommendationRuleSetService와 동일 관례):
- 서비스는 생성자 인자를 받지 않는다.
- `@transaction`이 첫 번째 파라미터로 session을 주입하고 commit/rollback을 소유한다.
- Repository는 메서드 내부에서 생성하고 session을 파라미터로 전달한다(새 세션 계약).
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.database.repositories.access_log_repository import AccessLogRepository
from src.application.common.decorators import transaction
from src.application.domain.access_log.dto import (
    AccessLogCleanupResultDTO,
    AccessLogItemDTO,
    AccessLogListDTO,
    AccessLogStatsDTO,
    AccessLogUniqueIpsDTO,
)

# 통계 응답에 포함하는 시간대 버킷 수(최근 24시간). 기존 라우터의 hourly_stats[:24]와 동일.
HOURLY_STATS_LIMIT = 24

# 통계 상위 N (기존 라우터가 repository에 넘기던 limit=10과 동일)
TOP_STATS_LIMIT = 10


class AccessLogService:
    """접근 로그 조회/통계/정리 서비스"""

    @transaction
    async def get_recent_logs(
        self,
        session: AsyncSession,
        limit: int = 100,
        offset: int = 0,
        path_filter: str | None = None,
        ip_filter: str | None = None,
    ) -> AccessLogListDTO:
        """최근 접근 로그 목록 조회"""
        repo = AccessLogRepository()
        logs = await repo.get_recent_logs(
            limit=limit,
            offset=offset,
            path_filter=path_filter,
            ip_filter=ip_filter,
            session=session,
        )
        items = [
            AccessLogItemDTO(
                id=log.id,
                method=log.method,
                path=log.path,
                query_string=log.query_string,
                ip_address=log.ip_address,
                user_agent=log.user_agent,
                referer=log.referer,
                status_code=log.status_code,
                response_time_ms=log.response_time_ms,
                accessed_at=log.accessed_at.isoformat() if log.accessed_at else None,
                country=log.country,
                city=log.city,
            )
            for log in logs
        ]
        return AccessLogListDTO(
            items=items,
            count=len(items),
            limit=limit,
            offset=offset,
        )

    @transaction
    async def get_stats(self, session: AsyncSession, hours: int = 24) -> AccessLogStatsDTO:
        """지정 기간 접근 통계 조회"""
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        repo = AccessLogRepository()

        # 전체 개수
        total_count = await repo.get_total_count(since=since, session=session)

        # 고유 IP 수
        unique_ips = await repo.get_unique_ips(since=since, session=session)

        # 경로별 통계
        path_stats = await repo.get_path_stats(since=since, limit=TOP_STATS_LIMIT, session=session)

        # IP별 통계
        ip_stats = await repo.get_ip_stats(since=since, limit=TOP_STATS_LIMIT, session=session)

        # 시간대별 통계
        hourly_stats = await repo.get_hourly_stats(since=since, session=session)

        return AccessLogStatsDTO(
            period_hours=hours,
            since=since.isoformat(),
            total_requests=total_count,
            unique_visitors=len(unique_ips),
            path_stats=path_stats,
            ip_stats=ip_stats,
            hourly_stats=hourly_stats[:HOURLY_STATS_LIMIT],  # 최근 24시간
        )

    @transaction
    async def get_unique_ips(self, session: AsyncSession, hours: int = 24) -> AccessLogUniqueIpsDTO:
        """지정 기간 고유 IP 목록 조회"""
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        repo = AccessLogRepository()
        ips = await repo.get_unique_ips(since=since, session=session)
        return AccessLogUniqueIpsDTO(
            period_hours=hours,
            since=since.isoformat(),
            unique_ips=ips,
            count=len(ips),
        )

    @transaction
    async def cleanup_old_logs(
        self, session: AsyncSession, days: int = 30
    ) -> AccessLogCleanupResultDTO:
        """보관 기간이 지난 로그 삭제 (@transaction이 commit을 담당)"""
        before = datetime.now(timezone.utc) - timedelta(days=days)
        repo = AccessLogRepository()
        deleted_count = await repo.delete_old_logs(before=before, session=session)
        return AccessLogCleanupResultDTO(
            deleted_count=deleted_count,
            before=before.isoformat(),
        )
