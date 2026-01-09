# -*- coding: utf-8 -*-
"""
OHLCV Cache Manager - OHLCV 캐시 수명주기 관리

데이터 정리, 무결성 검증, 결측 구간 탐지 등 캐시 관리 기능 제공
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.database.repositories.ohlcv_repository import OHLCVRepository
from src.application.domain.ohlcv.dto import (
    CacheRetentionPolicyDTO,
    CleanupResultDTO,
    GapInfoDTO,
    SymbolGapsDTO,
)

logger = logging.getLogger(__name__)


# 한국 공휴일 (간단 버전 - 필요시 확장)
KOREA_HOLIDAYS_2024 = {
    datetime(2024, 1, 1),   # 신정
    datetime(2024, 2, 9),   # 설날 연휴
    datetime(2024, 2, 10),  # 설날
    datetime(2024, 2, 11),  # 설날 연휴
    datetime(2024, 2, 12),  # 대체휴일
    datetime(2024, 3, 1),   # 삼일절
    datetime(2024, 4, 10),  # 국회의원선거
    datetime(2024, 5, 5),   # 어린이날
    datetime(2024, 5, 6),   # 대체휴일
    datetime(2024, 5, 15),  # 부처님오신날
    datetime(2024, 6, 6),   # 현충일
    datetime(2024, 8, 15),  # 광복절
    datetime(2024, 9, 16),  # 추석 연휴
    datetime(2024, 9, 17),  # 추석
    datetime(2024, 9, 18),  # 추석 연휴
    datetime(2024, 10, 3),  # 개천절
    datetime(2024, 10, 9),  # 한글날
    datetime(2024, 12, 25), # 성탄절
}

KOREA_HOLIDAYS_2025 = {
    datetime(2025, 1, 1),   # 신정
    datetime(2025, 1, 28),  # 설날 연휴
    datetime(2025, 1, 29),  # 설날
    datetime(2025, 1, 30),  # 설날 연휴
    datetime(2025, 3, 1),   # 삼일절
    datetime(2025, 5, 5),   # 어린이날
    datetime(2025, 5, 6),   # 부처님오신날
    datetime(2025, 6, 6),   # 현충일
    datetime(2025, 8, 15),  # 광복절
    datetime(2025, 10, 3),  # 개천절
    datetime(2025, 10, 5),  # 추석 연휴
    datetime(2025, 10, 6),  # 추석
    datetime(2025, 10, 7),  # 추석 연휴
    datetime(2025, 10, 8),  # 대체휴일
    datetime(2025, 10, 9),  # 한글날
    datetime(2025, 12, 25), # 성탄절
}

KOREA_HOLIDAYS_2026 = {
    datetime(2026, 1, 1),   # 신정
    datetime(2026, 2, 16),  # 설날 연휴
    datetime(2026, 2, 17),  # 설날
    datetime(2026, 2, 18),  # 설날 연휴
    datetime(2026, 3, 1),   # 삼일절
    datetime(2026, 3, 2),   # 대체휴일
    datetime(2026, 5, 5),   # 어린이날
    datetime(2026, 5, 24),  # 부처님오신날
    datetime(2026, 5, 25),  # 대체휴일
    datetime(2026, 6, 6),   # 현충일
    datetime(2026, 8, 15),  # 광복절
    datetime(2026, 8, 17),  # 대체휴일
    datetime(2026, 9, 24),  # 추석 연휴
    datetime(2026, 9, 25),  # 추석
    datetime(2026, 9, 26),  # 추석 연휴
    datetime(2026, 10, 3),  # 개천절
    datetime(2026, 10, 5),  # 대체휴일
    datetime(2026, 10, 9),  # 한글날
    datetime(2026, 12, 25), # 성탄절
}

KOREA_HOLIDAYS = KOREA_HOLIDAYS_2024 | KOREA_HOLIDAYS_2025 | KOREA_HOLIDAYS_2026


class OHLCVCacheManager:
    """
    OHLCV 캐시 수명주기 관리

    데이터 정리, 무결성 검증, 결측 구간 탐지 등
    """

    def __init__(self, session: AsyncSession) -> None:
        """
        Args:
            session: Database Session
        """
        self.session = session
        self.ohlcv_repo = OHLCVRepository(session)

    # ==================== 데이터 정리 ====================

    async def cleanup_old_data(
        self,
        policy: CacheRetentionPolicyDTO | None = None,
        dry_run: bool = True,
    ) -> CleanupResultDTO:
        """
        보존 정책에 따라 오래된 데이터 삭제

        Args:
            policy: 보존 정책 (None이면 기본값 사용)
            dry_run: True면 삭제하지 않고 예상 결과만 반환

        Returns:
            CleanupResultDTO: 정리 결과
        """
        import time

        start_time = time.time()

        if policy is None:
            policy = CacheRetentionPolicyDTO()

        before_date = datetime.now() - timedelta(days=policy.retention_days)

        # 영향받을 종목 조회
        symbols = await self.ohlcv_repo.get_all_symbols()
        affected_symbols = []

        for symbol in symbols:
            stats = await self.ohlcv_repo.get_symbol_stats(symbol)
            if stats["earliest_date"] and stats["earliest_date"] < before_date:
                affected_symbols.append(symbol)

        deleted_count = 0

        if not dry_run:
            deleted_count = await self.ohlcv_repo.bulk_delete_old_data(
                before_date=before_date,
                batch_size=policy.cleanup_batch_size,
            )
            await self.session.commit()

            logger.info(
                f"[CacheManager] Cleanup completed: {deleted_count} records deleted, "
                f"{len(affected_symbols)} symbols affected"
            )

        duration = time.time() - start_time

        return CleanupResultDTO(
            deleted_count=deleted_count,
            symbols_affected=affected_symbols,
            before_date=before_date,
            dry_run=dry_run,
            duration_seconds=round(duration, 2),
        )

    async def cleanup_symbol(
        self,
        symbol: str,
        before_date: datetime,
        interval: str = "1d",
    ) -> int:
        """
        특정 종목의 오래된 데이터 삭제

        Args:
            symbol: 종목코드
            before_date: 기준 날짜
            interval: 캔들 간격

        Returns:
            int: 삭제된 레코드 수
        """
        deleted = await self.ohlcv_repo.delete_old_data(
            symbol=symbol,
            before_date=before_date,
            interval=interval,
        )

        if deleted > 0:
            logger.info(
                f"[CacheManager] Cleaned up {deleted} old records for {symbol}"
            )

        return deleted

    # ==================== 무결성 검증 ====================

    async def validate_data_integrity(
        self,
        symbol: str,
        interval: str = "1d",
    ) -> dict:
        """
        데이터 무결성 검증

        - OHLC 관계 (High >= Open/Close >= Low)
        - 중복 데이터

        Args:
            symbol: 종목코드
            interval: 캔들 간격

        Returns:
            dict: {"is_valid": bool, "issues": list}
        """
        issues = []

        # 데이터 조회 (최근 1년)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365)

        candles = await self.ohlcv_repo.get_candles_by_date_range(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            interval=interval,
        )

        if not candles:
            return {"is_valid": True, "issues": [], "message": "No data to validate"}

        # OHLC 관계 검증
        for candle in candles:
            high = float(candle.high)
            low = float(candle.low)
            open_price = float(candle.open)
            close = float(candle.close)

            if high < max(open_price, close):
                issues.append(
                    f"High < max(Open, Close) at {candle.timestamp}: "
                    f"H={high}, O={open_price}, C={close}"
                )

            if low > min(open_price, close):
                issues.append(
                    f"Low > min(Open, Close) at {candle.timestamp}: "
                    f"L={low}, O={open_price}, C={close}"
                )

        # 중복 날짜 검증
        timestamps = [candle.timestamp for candle in candles]
        seen = set()
        duplicates = []
        for ts in timestamps:
            if ts in seen:
                duplicates.append(ts)
            seen.add(ts)

        if duplicates:
            issues.append(f"Duplicate timestamps found: {len(duplicates)}")

        return {
            "is_valid": len(issues) == 0,
            "issues": issues[:10],  # 최대 10개만 반환
            "total_issues": len(issues),
            "candles_checked": len(candles),
        }

    # ==================== 결측 구간 탐지 ====================

    async def detect_gaps(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        interval: str = "1d",
    ) -> SymbolGapsDTO:
        """
        결측 구간 탐지 (거래일 기준)

        주말/공휴일을 고려한 실제 결측 구간만 반환

        Args:
            symbol: 종목코드
            start_date: 시작일
            end_date: 종료일
            interval: 캔들 간격

        Returns:
            SymbolGapsDTO: 결측 구간 정보
        """
        candles = await self.ohlcv_repo.get_candles_by_date_range(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            interval=interval,
        )

        if not candles:
            # 전체 구간이 결측
            trading_days = self.get_trading_days_between(start_date, end_date)
            return SymbolGapsDTO(
                symbol=symbol,
                gaps=[
                    GapInfoDTO(
                        symbol=symbol,
                        start_date=start_date,
                        end_date=end_date,
                        trading_days_missing=len(trading_days),
                    )
                ],
                total_missing_days=len(trading_days),
                has_gaps=True,
            )

        # 캐시된 날짜 집합
        cached_dates = {
            candle.timestamp.replace(tzinfo=None).date()
            if candle.timestamp.tzinfo
            else candle.timestamp.date()
            for candle in candles
        }

        # 기대되는 거래일
        trading_days = self.get_trading_days_between(start_date, end_date)
        expected_dates = {day.date() for day in trading_days}

        # 결측 날짜
        missing_dates = sorted(expected_dates - cached_dates)

        if not missing_dates:
            return SymbolGapsDTO(
                symbol=symbol,
                gaps=[],
                total_missing_days=0,
                has_gaps=False,
            )

        # 연속된 결측 구간으로 그룹화
        gaps = []
        if missing_dates:
            gap_start = missing_dates[0]
            gap_end = missing_dates[0]

            for i in range(1, len(missing_dates)):
                current = missing_dates[i]
                prev = missing_dates[i - 1]

                # 연속 여부 확인 (거래일 기준 1일 차이)
                if (current - prev).days <= 3:  # 주말 고려
                    gap_end = current
                else:
                    gaps.append(
                        GapInfoDTO(
                            symbol=symbol,
                            start_date=datetime.combine(gap_start, datetime.min.time()),
                            end_date=datetime.combine(gap_end, datetime.min.time()),
                            trading_days_missing=self._count_trading_days_in_range(
                                gap_start, gap_end, missing_dates
                            ),
                        )
                    )
                    gap_start = current
                    gap_end = current

            # 마지막 구간 추가
            gaps.append(
                GapInfoDTO(
                    symbol=symbol,
                    start_date=datetime.combine(gap_start, datetime.min.time()),
                    end_date=datetime.combine(gap_end, datetime.min.time()),
                    trading_days_missing=self._count_trading_days_in_range(
                        gap_start, gap_end, missing_dates
                    ),
                )
            )

        return SymbolGapsDTO(
            symbol=symbol,
            gaps=gaps,
            total_missing_days=len(missing_dates),
            has_gaps=len(gaps) > 0,
        )

    def _count_trading_days_in_range(
        self,
        start_date,
        end_date,
        missing_dates: list,
    ) -> int:
        """구간 내 결측 거래일 수 계산"""
        return sum(
            1 for d in missing_dates
            if start_date <= d <= end_date
        )

    # ==================== 거래일 캘린더 ====================

    def is_trading_day(self, date: datetime) -> bool:
        """
        거래일 여부 확인 (주말 + 한국 공휴일 제외)

        Args:
            date: 확인할 날짜

        Returns:
            bool: 거래일 여부
        """
        # 주말 확인
        if date.weekday() >= 5:  # 토요일(5), 일요일(6)
            return False

        # 공휴일 확인
        date_only = datetime(date.year, date.month, date.day)
        if date_only in KOREA_HOLIDAYS:
            return False

        return True

    def get_trading_days_between(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> list[datetime]:
        """
        기간 내 거래일 목록 반환

        Args:
            start_date: 시작일
            end_date: 종료일

        Returns:
            list[datetime]: 거래일 목록
        """
        trading_days = []
        current = start_date

        while current <= end_date:
            if self.is_trading_day(current):
                trading_days.append(current)
            current += timedelta(days=1)

        return trading_days

    def estimate_trading_days(self, days: int) -> int:
        """
        캘린더 일수에서 예상 거래일 수 계산

        대략 연간 250일 거래일 기준 (주말 제외 + 공휴일 약 15일)

        Args:
            days: 캘린더 일수

        Returns:
            int: 예상 거래일 수
        """
        # 연간 약 365일 중 250일 거래 → 비율 0.685
        return int(days * 0.685)
