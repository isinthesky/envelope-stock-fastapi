# -*- coding: utf-8 -*-
"""
Access Log Router - 접근 로그 API

외부 접근 로그 조회 API를 제공합니다.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query

from src.adapters.database.connection import get_async_session
from src.adapters.database.repositories.access_log_repository import AccessLogRepository
from src.application.common.dependencies import AdminAccessDep
from src.application.common.dto import ResponseDTO

router = APIRouter(prefix="/api/v1/access-logs", tags=["AccessLogs"])


@router.get("", response_model=ResponseDTO)
async def get_access_logs(
    limit: int = Query(default=100, ge=1, le=500, description="조회 개수"),
    offset: int = Query(default=0, ge=0, description="시작 위치"),
    path_filter: str | None = Query(default=None, description="경로 필터"),
    ip_filter: str | None = Query(default=None, description="IP 필터"),
    admin_access: AdminAccessDep = None,
) -> ResponseDTO:
    """
    접근 로그 목록 조회

    최근 접근 로그를 조회합니다.
    """
    async with get_async_session() as session:
        repo = AccessLogRepository()
        logs = await repo.get_recent_logs(
            limit=limit,
            offset=offset,
            path_filter=path_filter,
            ip_filter=ip_filter,
            session=session,
        )

        return ResponseDTO.success_response(
            data={
                "items": [
                    {
                        "id": log.id,
                        "method": log.method,
                        "path": log.path,
                        "query_string": log.query_string,
                        "ip_address": log.ip_address,
                        "user_agent": log.user_agent,
                        "referer": log.referer,
                        "status_code": log.status_code,
                        "response_time_ms": log.response_time_ms,
                        "accessed_at": log.accessed_at.isoformat() if log.accessed_at else None,
                        "country": log.country,
                        "city": log.city,
                    }
                    for log in logs
                ],
                "count": len(logs),
                "limit": limit,
                "offset": offset,
            }
        )


@router.get("/stats", response_model=ResponseDTO)
async def get_access_stats(
    hours: int = Query(default=24, ge=1, le=168, description="통계 기간 (시간)"),
    admin_access: AdminAccessDep = None,
) -> ResponseDTO:
    """
    접근 통계 조회

    지정된 기간 동안의 접근 통계를 조회합니다.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    async with get_async_session() as session:
        repo = AccessLogRepository()

        # 전체 개수
        total_count = await repo.get_total_count(since=since, session=session)

        # 고유 IP 수
        unique_ips = await repo.get_unique_ips(since=since, session=session)

        # 경로별 통계
        path_stats = await repo.get_path_stats(since=since, limit=10, session=session)

        # IP별 통계
        ip_stats = await repo.get_ip_stats(since=since, limit=10, session=session)

        # 시간대별 통계
        hourly_stats = await repo.get_hourly_stats(since=since, session=session)

        return ResponseDTO.success_response(
            data={
                "period_hours": hours,
                "since": since.isoformat(),
                "total_requests": total_count,
                "unique_visitors": len(unique_ips),
                "path_stats": path_stats,
                "ip_stats": ip_stats,
                "hourly_stats": hourly_stats[:24],  # 최근 24시간
            }
        )


@router.get("/unique-ips", response_model=ResponseDTO)
async def get_unique_ips(
    hours: int = Query(default=24, ge=1, le=168, description="기간 (시간)"),
    admin_access: AdminAccessDep = None,
) -> ResponseDTO:
    """
    고유 IP 목록 조회

    지정된 기간 동안 접속한 고유 IP 목록을 조회합니다.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    async with get_async_session() as session:
        repo = AccessLogRepository()
        ips = await repo.get_unique_ips(since=since, session=session)

        return ResponseDTO.success_response(
            data={
                "period_hours": hours,
                "since": since.isoformat(),
                "unique_ips": ips,
                "count": len(ips),
            }
        )


@router.delete("/cleanup", response_model=ResponseDTO)
async def cleanup_old_logs(
    days: int = Query(default=30, ge=7, le=365, description="보관 기간 (일)"),
    admin_access: AdminAccessDep = None,
) -> ResponseDTO:
    """
    오래된 로그 정리

    지정된 일수 이전의 로그를 삭제합니다.
    """
    before = datetime.now(timezone.utc) - timedelta(days=days)

    async with get_async_session() as session:
        repo = AccessLogRepository()
        deleted_count = await repo.delete_old_logs(before=before, session=session)
        await session.commit()

        return ResponseDTO.success_response(
            data={
                "deleted_count": deleted_count,
                "before": before.isoformat(),
            },
            message=f"{deleted_count}개의 오래된 로그가 삭제되었습니다.",
        )
