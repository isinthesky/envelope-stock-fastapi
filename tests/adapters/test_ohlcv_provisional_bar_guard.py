"""장 마감 전 당일 일봉(잠정값) 저장 차단 회귀 테스트 (2026-11-06)."""

from datetime import datetime, timedelta, timezone

from src.application.common.trading_calendar import KST_ZONE, is_provisional_daily_bar

UTC = timezone.utc


def _bar(day: datetime) -> datetime:
    """일봉 캐시 관례: 해당 KST 날짜의 00:00 UTC."""
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def test_same_day_bar_before_close_is_provisional() -> None:
    now = datetime(2026, 11, 6, 12, 29, tzinfo=KST_ZONE)
    assert is_provisional_daily_bar(_bar(now), now)
    assert is_provisional_daily_bar(_bar(now).replace(tzinfo=None), now)  # naive = UTC


def test_same_day_bar_after_close_and_past_bars_are_final() -> None:
    after = datetime(2026, 11, 6, 15, 31, tzinfo=KST_ZONE)
    assert not is_provisional_daily_bar(_bar(after), after)
    morning = datetime(2026, 11, 6, 8, 0, tzinfo=KST_ZONE)
    assert not is_provisional_daily_bar(_bar(morning - timedelta(days=1)), morning)


def test_kst_date_boundary_uses_kst_not_utc() -> None:
    # 2026-11-07 00:30 KST(= 11-06 15:30 UTC): 11-07 봉은 잠정, 11-06 봉은 확정
    now = datetime(2026, 11, 7, 0, 30, tzinfo=KST_ZONE)
    assert is_provisional_daily_bar(datetime(2026, 11, 7, tzinfo=UTC), now)
    assert not is_provisional_daily_bar(datetime(2026, 11, 6, tzinfo=UTC), now)
