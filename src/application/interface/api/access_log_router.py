# -*- coding: utf-8 -*-
"""
Access Log Router - 접근 로그 API

외부 접근 로그 조회 API를 제공합니다.

레이어 규칙: 라우터는 세션/Repository를 직접 다루지 않고 AccessLogService만 호출합니다.
"""

from fastapi import APIRouter, Query

from src.application.common.dependencies import AdminAccessDep
from src.application.common.dto import ResponseDTO
from src.application.domain.access_log.dto import (
    AccessLogCleanupResultDTO,
    AccessLogListDTO,
    AccessLogStatsDTO,
    AccessLogUniqueIpsDTO,
)
from src.application.domain.access_log.service import AccessLogService

router = APIRouter(prefix="/api/v1/access-logs", tags=["AccessLogs"])


@router.get("", response_model=ResponseDTO[AccessLogListDTO])
async def get_access_logs(
    limit: int = Query(default=100, ge=1, le=500, description="조회 개수"),
    offset: int = Query(default=0, ge=0, description="시작 위치"),
    path_filter: str | None = Query(default=None, description="경로 필터"),
    ip_filter: str | None = Query(default=None, description="IP 필터"),
    admin_access: AdminAccessDep = None,
) -> ResponseDTO[AccessLogListDTO]:
    """
    접근 로그 목록 조회

    최근 접근 로그를 조회합니다.
    """
    _ = admin_access
    service = AccessLogService()
    result = await service.get_recent_logs(
        limit=limit,
        offset=offset,
        path_filter=path_filter,
        ip_filter=ip_filter,
    )
    return ResponseDTO.success_response(data=result)


@router.get("/stats", response_model=ResponseDTO[AccessLogStatsDTO])
async def get_access_stats(
    hours: int = Query(default=24, ge=1, le=168, description="통계 기간 (시간)"),
    admin_access: AdminAccessDep = None,
) -> ResponseDTO[AccessLogStatsDTO]:
    """
    접근 통계 조회

    지정된 기간 동안의 접근 통계를 조회합니다.
    """
    _ = admin_access
    service = AccessLogService()
    result = await service.get_stats(hours=hours)
    return ResponseDTO.success_response(data=result)


@router.get("/unique-ips", response_model=ResponseDTO[AccessLogUniqueIpsDTO])
async def get_unique_ips(
    hours: int = Query(default=24, ge=1, le=168, description="기간 (시간)"),
    admin_access: AdminAccessDep = None,
) -> ResponseDTO[AccessLogUniqueIpsDTO]:
    """
    고유 IP 목록 조회

    지정된 기간 동안 접속한 고유 IP 목록을 조회합니다.
    """
    _ = admin_access
    service = AccessLogService()
    result = await service.get_unique_ips(hours=hours)
    return ResponseDTO.success_response(data=result)


@router.delete("/cleanup", response_model=ResponseDTO[AccessLogCleanupResultDTO])
async def cleanup_old_logs(
    days: int = Query(default=30, ge=7, le=365, description="보관 기간 (일)"),
    admin_access: AdminAccessDep = None,
) -> ResponseDTO[AccessLogCleanupResultDTO]:
    """
    오래된 로그 정리

    지정된 일수 이전의 로그를 삭제합니다.
    """
    _ = admin_access
    service = AccessLogService()
    result = await service.cleanup_old_logs(days=days)
    return ResponseDTO.success_response(
        data=result,
        message=f"{result.deleted_count}개의 오래된 로그가 삭제되었습니다.",
    )
