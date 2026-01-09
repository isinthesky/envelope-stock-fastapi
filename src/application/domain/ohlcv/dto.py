# -*- coding: utf-8 -*-
"""
OHLCV Cache DTO - OHLCV 캐시 관련 데이터 전송 객체
"""

from datetime import datetime

from pydantic import Field

from src.application.common.dto import BaseDTO


# ==================== 캐시 보존 정책 ====================


class CacheRetentionPolicyDTO(BaseDTO):
    """
    캐시 보존 정책 DTO

    Attributes:
        retention_days: 기본 보존 기간 (일)
        min_recent_days: 최소 최근 데이터 유지 기간 (일)
        cleanup_batch_size: 배치 삭제 크기
    """

    retention_days: int = Field(default=365, ge=30, description="기본 보존 기간 (일)")
    min_recent_days: int = Field(default=90, ge=30, description="최소 최근 데이터 유지 기간")
    cleanup_batch_size: int = Field(default=1000, ge=100, description="배치 삭제 크기")


# ==================== 캐시 통계 ====================


class SymbolCacheInfoDTO(BaseDTO):
    """
    종목별 캐시 정보 DTO

    Attributes:
        symbol: 종목코드
        candle_count: 캔들 개수
        earliest_date: 가장 오래된 날짜
        latest_date: 가장 최근 날짜
        interval: 캔들 간격
    """

    symbol: str = Field(description="종목코드")
    candle_count: int = Field(description="캔들 개수")
    earliest_date: datetime | None = Field(default=None, description="가장 오래된 날짜")
    latest_date: datetime | None = Field(default=None, description="가장 최근 날짜")
    interval: str = Field(default="1d", description="캔들 간격")


class CacheStatisticsDTO(BaseDTO):
    """
    전체 캐시 통계 DTO

    Attributes:
        total_symbols: 캐시된 종목 수
        total_candles: 전체 캔들 수
        oldest_data_date: 가장 오래된 데이터 날짜
        newest_data_date: 가장 최근 데이터 날짜
        cache_size_mb: 추정 캐시 크기 (MB)
        symbols_by_interval: 간격별 종목 수
        intervals: 캐시된 간격 목록
    """

    total_symbols: int = Field(description="캐시된 종목 수")
    total_candles: int = Field(description="전체 캔들 수")
    oldest_data_date: datetime | None = Field(default=None, description="가장 오래된 데이터")
    newest_data_date: datetime | None = Field(default=None, description="가장 최근 데이터")
    cache_size_mb: float = Field(default=0.0, description="추정 캐시 크기 (MB)")
    symbols_by_interval: dict[str, int] = Field(
        default_factory=dict, description="간격별 종목 수"
    )
    intervals: list[str] = Field(default_factory=list, description="캐시된 간격 목록")


# ==================== 캐시 건강 상태 ====================


class CacheHealthDTO(BaseDTO):
    """
    캐시 건강 상태 DTO

    Attributes:
        is_healthy: 건강 상태 여부
        stale_symbols: 오래된 데이터 보유 종목 목록
        stale_count: 오래된 데이터 종목 수
        missing_recent_data: 최근 데이터 없는 종목 목록
        gap_detected: 결측 구간 있는 종목 목록
        recommendations: 권장 조치 목록
        checked_at: 확인 시각
    """

    is_healthy: bool = Field(description="건강 상태 여부")
    stale_symbols: list[str] = Field(default_factory=list, description="오래된 데이터 종목")
    stale_count: int = Field(default=0, description="오래된 데이터 종목 수")
    missing_recent_data: list[str] = Field(
        default_factory=list, description="최근 데이터 없는 종목"
    )
    gap_detected: list[str] = Field(default_factory=list, description="결측 구간 있는 종목")
    recommendations: list[str] = Field(default_factory=list, description="권장 조치")
    checked_at: datetime = Field(default_factory=datetime.now, description="확인 시각")


# ==================== 워밍업 요청/결과 ====================


class WarmupRequestDTO(BaseDTO):
    """
    워밍업 요청 DTO

    Attributes:
        symbols: 워밍업 대상 종목 목록
        days: 조회 기간 (일)
        interval: 캔들 간격
        priority: 우선순위 (high, normal, low)
        force_refresh: 기존 캐시 무시 여부
    """

    symbols: list[str] = Field(description="워밍업 대상 종목 목록")
    days: int = Field(default=240, ge=1, le=500, description="조회 기간 (일)")
    interval: str = Field(default="1d", description="캔들 간격")
    priority: str = Field(default="normal", pattern="^(high|normal|low)$", description="우선순위")
    force_refresh: bool = Field(default=False, description="기존 캐시 무시 여부")


class WarmupResultDTO(BaseDTO):
    """
    워밍업 결과 DTO

    Attributes:
        total_symbols: 총 요청 종목 수
        success_count: 성공 종목 수
        failed_count: 실패 종목 수
        skipped_count: 스킵 종목 수 (이미 최신)
        api_calls_made: API 호출 횟수
        candles_cached: 캐시된 캔들 수
        duration_seconds: 소요 시간 (초)
        errors: 에러 목록
    """

    total_symbols: int = Field(description="총 요청 종목 수")
    success_count: int = Field(default=0, description="성공 종목 수")
    failed_count: int = Field(default=0, description="실패 종목 수")
    skipped_count: int = Field(default=0, description="스킵 종목 수")
    api_calls_made: int = Field(default=0, description="API 호출 횟수")
    candles_cached: int = Field(default=0, description="캐시된 캔들 수")
    duration_seconds: float = Field(default=0.0, description="소요 시간 (초)")
    errors: list[str] = Field(default_factory=list, description="에러 목록")


# ==================== 데이터 정리 결과 ====================


class CleanupResultDTO(BaseDTO):
    """
    데이터 정리 결과 DTO

    Attributes:
        deleted_count: 삭제된 레코드 수
        symbols_affected: 영향받은 종목 목록
        before_date: 기준 날짜
        dry_run: 시뮬레이션 여부
        duration_seconds: 소요 시간 (초)
    """

    deleted_count: int = Field(default=0, description="삭제된 레코드 수")
    symbols_affected: list[str] = Field(default_factory=list, description="영향받은 종목")
    before_date: datetime = Field(description="기준 날짜")
    dry_run: bool = Field(default=True, description="시뮬레이션 여부")
    duration_seconds: float = Field(default=0.0, description="소요 시간 (초)")


# ==================== 결측 구간 ====================


class GapInfoDTO(BaseDTO):
    """
    결측 구간 정보 DTO

    Attributes:
        symbol: 종목코드
        start_date: 결측 시작일
        end_date: 결측 종료일
        trading_days_missing: 누락된 거래일 수 (추정)
    """

    symbol: str = Field(description="종목코드")
    start_date: datetime = Field(description="결측 시작일")
    end_date: datetime = Field(description="결측 종료일")
    trading_days_missing: int = Field(default=0, description="누락된 거래일 수 (추정)")


class SymbolGapsDTO(BaseDTO):
    """
    종목 결측 구간 DTO

    Attributes:
        symbol: 종목코드
        gaps: 결측 구간 목록
        total_missing_days: 총 누락 거래일 수 (추정)
        has_gaps: 결측 여부
    """

    symbol: str = Field(description="종목코드")
    gaps: list[GapInfoDTO] = Field(default_factory=list, description="결측 구간 목록")
    total_missing_days: int = Field(default=0, description="총 누락 거래일 수")
    has_gaps: bool = Field(default=False, description="결측 여부")


# ==================== API 호출 예상치 ====================


class ApiCallEstimateDTO(BaseDTO):
    """
    API 호출 예상치 DTO

    Attributes:
        total_symbols: 총 종목 수
        cached_symbols: 캐시된 종목 수
        api_calls_needed: 필요한 API 호출 수
        estimated_time_seconds: 예상 소요 시간 (초)
        estimated_time_formatted: 예상 소요 시간 (포맷)
    """

    total_symbols: int = Field(description="총 종목 수")
    cached_symbols: int = Field(default=0, description="캐시된 종목 수")
    api_calls_needed: int = Field(default=0, description="필요한 API 호출 수")
    estimated_time_seconds: float = Field(default=0.0, description="예상 소요 시간 (초)")
    estimated_time_formatted: str = Field(default="", description="예상 소요 시간 (포맷)")
