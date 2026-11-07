# -*- coding: utf-8 -*-
"""
Trading Calendar - 한국 주식시장 거래일 계산

python holidays 라이브러리 기반 공휴일 관리
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

try:
    import holidays
except ImportError:
    raise ImportError(
        "holidays 라이브러리가 필요합니다. 설치: pip install holidays"
    )


class TradingCalendar:
    """
    한국 주식시장 거래일 계산

    주말(토/일) + 한국 공휴일 제외하여 거래일 판단
    """

    def __init__(self, country: str = "KR") -> None:
        """
        Args:
            country: 국가 코드 (기본값: "KR" - 대한민국)
        """
        self.country = country
        # holidays 라이브러리로 한국 공휴일 로드
        # years 파라미터를 사용하면 특정 연도만 로드할 수 있지만
        # 생략하면 필요 시 자동으로 해당 연도 데이터를 로드
        self.holidays = holidays.country_holidays(country)

    def is_trading_day(self, date: datetime) -> bool:
        """
        거래일 여부 확인 (주말 + 공휴일 제외)

        Args:
            date: 확인할 날짜

        Returns:
            bool: 거래일 여부
        """
        # 주말 확인
        if date.weekday() >= 5:  # 토요일(5), 일요일(6)
            return False

        # 공휴일 확인
        # holidays 라이브러리는 datetime, date 모두 지원
        if date in self.holidays:
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

        한국 주식시장 기준:
        - 연간 약 365일 중 250일 거래
        - 비율: 250/365 ≈ 0.685

        Args:
            days: 캘린더 일수

        Returns:
            int: 예상 거래일 수
        """
        return int(days * 0.685)


# ==================== 팩토리 함수 (싱글톤 패턴) ====================

_calendar_instance: Optional[TradingCalendar] = None


def get_trading_calendar(country: str = "KR") -> TradingCalendar:
    """
    TradingCalendar 싱글톤 인스턴스 반환

    Args:
        country: 국가 코드 (기본값: "KR")

    Returns:
        TradingCalendar: 싱글톤 인스턴스
    """
    global _calendar_instance

    if _calendar_instance is None:
        _calendar_instance = TradingCalendar(country=country)

    return _calendar_instance


# ==================== 일봉 확정 판정 ====================

KST_ZONE = timezone(timedelta(hours=9), "KST")
# 정규장 15:30 종가(동시호가) 확정 직후. 이 시각 전의 당일 일봉은 잠정(장중/장전) 값이다(15:35 전략 실행은 확정 봉 사용).
DAILY_BAR_FINAL_TIME_KST = (15, 31)


def is_provisional_daily_bar(bar_timestamp: datetime, now: datetime | None = None) -> bool:
    """당일(KST) 일봉이 아직 확정 전인지.

    장중·장전에 받은 당일 일봉(현재가·누적거래량)을 확정 봉처럼 캐시하면, 이후 증분 업데이트가
    "오늘 봉이 이미 있음"으로 보고 덮어쓰지 않아 지표·신호가 잠정값으로 계산된다.
    naive timestamp는 UTC로 간주한다(일봉 캐시 관례: 00:00 UTC).
    """
    now_kst = (now or datetime.now(KST_ZONE)).astimezone(KST_ZONE)
    ts = bar_timestamp if bar_timestamp.tzinfo else bar_timestamp.replace(tzinfo=timezone.utc)
    if ts.astimezone(KST_ZONE).date() != now_kst.date():
        return False
    return (now_kst.hour, now_kst.minute) < DAILY_BAR_FINAL_TIME_KST
