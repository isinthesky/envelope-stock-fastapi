# -*- coding: utf-8 -*-
"""
OHLCV Router - OHLCV 캐시 관리 API 엔드포인트

캐시 통계, 건강 상태, 워밍업, 정리 작업 등
"""

from fastapi import APIRouter, Query, status

from src.application.common.dependencies import DatabaseSession
from src.application.common.dto import ResponseDTO
from src.application.domain.ohlcv.cache_manager import OHLCVCacheManager
from src.application.domain.ohlcv.dto import (
    CacheHealthDTO,
    CacheRetentionPolicyDTO,
    CacheStatisticsDTO,
    CleanupResultDTO,
    SymbolGapsDTO,
    WarmupRequestDTO,
    WarmupResultDTO,
)
from src.application.domain.ohlcv.statistics_service import OHLCVStatisticsService
from src.application.domain.ohlcv.warmup_service import OHLCVWarmupService

router = APIRouter()


# ==================== 통계 ====================


@router.get(
    "/statistics",
    response_model=ResponseDTO[CacheStatisticsDTO],
    status_code=status.HTTP_200_OK,
    summary="캐시 통계 조회",
    description="OHLCV 캐시 전체 통계 조회",
)
async def get_cache_statistics(
    session: DatabaseSession,
) -> ResponseDTO[CacheStatisticsDTO]:
    """캐시 통계 조회"""
    service = OHLCVStatisticsService(session)
    statistics = await service.get_cache_statistics()
    return ResponseDTO.success_response(statistics, "Cache statistics retrieved")


@router.get(
    "/health",
    response_model=ResponseDTO[CacheHealthDTO],
    status_code=status.HTTP_200_OK,
    summary="캐시 건강 상태 조회",
    description="OHLCV 캐시 건강 상태 진단",
)
async def get_cache_health(
    session: DatabaseSession,
    freshness_days: int = Query(default=7, ge=1, le=30, description="신선도 기준 (일)"),
) -> ResponseDTO[CacheHealthDTO]:
    """캐시 건강 상태 조회"""
    service = OHLCVStatisticsService(session)
    health = await service.get_cache_health(freshness_days)
    return ResponseDTO.success_response(health, "Cache health checked")


@router.get(
    "/freshness",
    response_model=ResponseDTO[dict],
    status_code=status.HTTP_200_OK,
    summary="데이터 신선도 요약",
    description="종목별 데이터 신선도 요약 정보",
)
async def get_freshness_summary(
    session: DatabaseSession,
    interval: str = Query(default="1d", description="캔들 간격"),
) -> ResponseDTO[dict]:
    """데이터 신선도 요약"""
    service = OHLCVStatisticsService(session)
    summary = await service.get_data_freshness_summary(interval)
    return ResponseDTO.success_response(summary, "Freshness summary retrieved")


# ==================== 워밍업 ====================


@router.post(
    "/warmup",
    response_model=ResponseDTO[WarmupResultDTO],
    status_code=status.HTTP_200_OK,
    summary="종목 캐시 워밍업",
    description="다중 종목 OHLCV 캐시 워밍업 (API 호출로 데이터 수집)",
)
async def warmup_symbols(
    request: WarmupRequestDTO,
    session: DatabaseSession,
    concurrency: int = Query(default=3, ge=1, le=10, description="동시 처리 수"),
) -> ResponseDTO[WarmupResultDTO]:
    """종목 캐시 워밍업"""
    service = OHLCVWarmupService(session)
    result = await service.warmup_symbols(request, concurrency)
    return ResponseDTO.success_response(result, "Warmup completed")


@router.post(
    "/warmup/universe",
    response_model=ResponseDTO[WarmupResultDTO],
    status_code=status.HTTP_200_OK,
    summary="유니버스 전체 워밍업",
    description="유니버스 내 모든 종목 캐시 워밍업",
)
async def warmup_universe(
    session: DatabaseSession,
    universe_id: int | None = Query(default=None, description="유니버스 ID (없으면 전체)"),
    days: int = Query(default=240, ge=1, le=500, description="조회 기간 (일)"),
    concurrency: int = Query(default=3, ge=1, le=10, description="동시 처리 수"),
) -> ResponseDTO[WarmupResultDTO]:
    """유니버스 전체 워밍업"""
    service = OHLCVWarmupService(session)
    universe_ids = [universe_id] if universe_id else None
    result = await service.warmup_universe(universe_ids, days, concurrency)
    return ResponseDTO.success_response(result, "Universe warmup completed")


@router.post(
    "/warmup/stale",
    response_model=ResponseDTO[WarmupResultDTO],
    status_code=status.HTTP_200_OK,
    summary="오래된 데이터 증분 업데이트",
    description="오래된 데이터를 가진 종목만 증분 업데이트",
)
async def update_stale_symbols(
    session: DatabaseSession,
    freshness_days: int = Query(default=3, ge=1, le=30, description="신선도 기준 (일)"),
    concurrency: int = Query(default=3, ge=1, le=10, description="동시 처리 수"),
) -> ResponseDTO[WarmupResultDTO]:
    """오래된 데이터 증분 업데이트"""
    service = OHLCVWarmupService(session)
    result = await service.update_stale_symbols(freshness_days, concurrency)
    return ResponseDTO.success_response(result, "Stale data updated")


@router.post(
    "/warmup/estimate",
    response_model=ResponseDTO[dict],
    status_code=status.HTTP_200_OK,
    summary="API 호출 예상치 계산",
    description="워밍업 시 필요한 API 호출 수 예상치 계산",
)
async def estimate_api_calls(
    request: WarmupRequestDTO,
    session: DatabaseSession,
) -> ResponseDTO[dict]:
    """API 호출 예상치 계산"""
    service = OHLCVStatisticsService(session)
    estimate = await service.get_api_call_estimate(
        symbols=request.symbols,
        days=request.days,
        interval=request.interval,
    )
    return ResponseDTO.success_response(estimate.model_dump(), "API call estimate calculated")


# ==================== 정리 ====================


@router.post(
    "/cleanup",
    response_model=ResponseDTO[CleanupResultDTO],
    status_code=status.HTTP_200_OK,
    summary="오래된 데이터 정리",
    description="보존 정책에 따라 오래된 캐시 데이터 삭제",
)
async def cleanup_old_data(
    session: DatabaseSession,
    policy: CacheRetentionPolicyDTO | None = None,
    dry_run: bool = Query(default=True, description="True면 삭제하지 않고 예상 결과만 반환"),
) -> ResponseDTO[CleanupResultDTO]:
    """오래된 데이터 정리"""
    manager = OHLCVCacheManager(session)
    result = await manager.cleanup_old_data(policy, dry_run)
    return ResponseDTO.success_response(result, "Cleanup completed" if not dry_run else "Dry run completed")


# ==================== 결측 구간 ====================


@router.get(
    "/{symbol}/gaps",
    response_model=ResponseDTO[SymbolGapsDTO],
    status_code=status.HTTP_200_OK,
    summary="종목 결측 구간 조회",
    description="특정 종목의 데이터 결측 구간 탐지",
)
async def get_symbol_gaps(
    symbol: str,
    session: DatabaseSession,
    days: int = Query(default=240, ge=1, le=500, description="조회 기간 (일)"),
    interval: str = Query(default="1d", description="캔들 간격"),
) -> ResponseDTO[SymbolGapsDTO]:
    """종목 결측 구간 조회"""
    from datetime import datetime, timedelta

    manager = OHLCVCacheManager(session)

    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    gaps = await manager.detect_gaps(symbol, start_date, end_date, interval)
    return ResponseDTO.success_response(gaps, "Gaps detected")


@router.get(
    "/{symbol}/stats",
    response_model=ResponseDTO[dict],
    status_code=status.HTTP_200_OK,
    summary="종목별 캐시 통계",
    description="특정 종목의 캐시 통계 조회",
)
async def get_symbol_stats(
    symbol: str,
    session: DatabaseSession,
    interval: str = Query(default="1d", description="캔들 간격"),
) -> ResponseDTO[dict]:
    """종목별 캐시 통계"""
    service = OHLCVStatisticsService(session)
    stats = await service.get_symbol_statistics(symbol, interval)
    return ResponseDTO.success_response(stats.model_dump(), "Symbol stats retrieved")


# ==================== 무결성 검증 ====================


@router.get(
    "/{symbol}/validate",
    response_model=ResponseDTO[dict],
    status_code=status.HTTP_200_OK,
    summary="데이터 무결성 검증",
    description="특정 종목의 OHLCV 데이터 무결성 검증",
)
async def validate_symbol_data(
    symbol: str,
    session: DatabaseSession,
    interval: str = Query(default="1d", description="캔들 간격"),
) -> ResponseDTO[dict]:
    """데이터 무결성 검증"""
    manager = OHLCVCacheManager(session)
    result = await manager.validate_data_integrity(symbol, interval)
    return ResponseDTO.success_response(result, "Validation completed")
