# -*- coding: utf-8 -*-
"""
OHLCV cleanup 잡 timezone 회귀 테스트

DB timestamptz(aware) earliest_date와 보존 기준일(before_date) 비교 시
naive/aware 혼용 TypeError가 재발하지 않는지 검증한다.

회귀 배경: cleanup 잡이 naive datetime.now() 기준일과 aware DB timestamp를
비교하다 "can't compare offset-naive and offset-aware datetimes"로 매일 실패.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from src.application.domain.ohlcv.cache_manager import OHLCVCacheManager
from src.application.domain.ohlcv.dto import CacheRetentionPolicyDTO


def _stats(earliest: datetime | None) -> dict:
    return {
        "total_candles": 100 if earliest else 0,
        "earliest_date": earliest,
        "latest_date": datetime.now(timezone.utc) if earliest else None,
        "date_range_days": 400 if earliest else 0,
    }


def _make_manager(
    earliest_by_symbol: dict[str, datetime | None],
) -> OHLCVCacheManager:
    session = MagicMock()
    session.commit = AsyncMock()
    manager = OHLCVCacheManager(session)

    repo = MagicMock()
    repo.get_all_symbols = AsyncMock(return_value=list(earliest_by_symbol))
    repo.get_symbol_stats = AsyncMock(
        side_effect=lambda symbol: _stats(earliest_by_symbol[symbol])
    )
    repo.bulk_delete_old_data = AsyncMock(return_value=42)
    manager.ohlcv_repo = repo
    return manager


class TestCleanupOldDataTimezone:
    async def test_cleanup_with_aware_earliest_date_does_not_raise(self) -> None:
        """DB가 aware(timestamptz) earliest_date를 반환해도 TypeError 없이 동작"""
        old_aware = datetime.now(timezone.utc) - timedelta(days=400)
        manager = _make_manager({"005930": old_aware})

        result = await manager.cleanup_old_data(
            CacheRetentionPolicyDTO(retention_days=365, cleanup_batch_size=1000),
            dry_run=False,
        )

        assert result.deleted_count == 42
        assert result.symbols_affected == ["005930"]
        assert result.before_date.tzinfo is not None
        manager.session.commit.assert_awaited_once()

    async def test_cleanup_normalizes_naive_earliest_date(self) -> None:
        """반대 방향 혼용(naive earliest_date)도 UTC로 정규화되어 비교 가능"""
        old_naive = datetime.now() - timedelta(days=400)
        manager = _make_manager({"000660": old_naive})

        result = await manager.cleanup_old_data(
            CacheRetentionPolicyDTO(retention_days=365, cleanup_batch_size=1000),
            dry_run=True,
        )

        assert result.symbols_affected == ["000660"]
        assert result.dry_run is True
        manager.ohlcv_repo.bulk_delete_old_data.assert_not_awaited()

    async def test_recent_symbol_not_affected(self) -> None:
        recent = datetime.now(timezone.utc) - timedelta(days=10)
        manager = _make_manager({"035420": recent})

        result = await manager.cleanup_old_data(dry_run=True)

        assert result.symbols_affected == []
        assert result.deleted_count == 0

    async def test_symbol_without_data_skipped(self) -> None:
        manager = _make_manager({"123456": None})

        result = await manager.cleanup_old_data(dry_run=True)

        assert result.symbols_affected == []
        assert result.deleted_count == 0

    async def test_before_date_is_utc_aware(self) -> None:
        """기준일은 항상 aware(UTC)로 생성되어야 한다"""
        manager = _make_manager({})

        result = await manager.cleanup_old_data(dry_run=True)

        assert result.before_date.tzinfo is not None
        assert result.before_date.utcoffset() == timedelta(0)
