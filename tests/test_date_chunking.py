# -*- coding: utf-8 -*-

from datetime import datetime, timedelta, timezone

import pytest

from src.application.domain.ohlcv.warmup_service import iter_date_chunks as iter_chunks_warmup
from src.application.domain.strategy.ohlcv_data_loader import iter_date_chunks as iter_chunks_loader


def _assert_chunks_ok(chunks, start, end, max_days: int):
    if start > end:
        assert chunks == []
        return

    assert chunks[0][0] == start
    assert chunks[-1][1] == end

    # no gaps / overlaps
    for (s1, e1), (s2, e2) in zip(chunks, chunks[1:]):
        assert s2 == e1 + timedelta(days=1)
        assert s2 <= e2

    # each chunk length <= max_days (inclusive)
    for s, e in chunks:
        assert (e - s).days + 1 <= max_days


@pytest.mark.parametrize("iter_fn", [iter_chunks_warmup, iter_chunks_loader])
def test_iter_date_chunks_empty_when_start_gt_end(iter_fn):
    start = datetime(2026, 1, 2, tzinfo=timezone.utc)
    end = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert iter_fn(start, end, 100) == []


@pytest.mark.parametrize("iter_fn", [iter_chunks_warmup, iter_chunks_loader])
def test_iter_date_chunks_exact_100_days(iter_fn):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(days=99)  # inclusive 100 days
    chunks = iter_fn(start, end, 100)
    assert len(chunks) == 1
    assert chunks[0] == (start, end)
    _assert_chunks_ok(chunks, start, end, 100)


@pytest.mark.parametrize("iter_fn", [iter_chunks_warmup, iter_chunks_loader])
def test_iter_date_chunks_101_days_splits(iter_fn):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(days=100)  # inclusive 101 days
    chunks = iter_fn(start, end, 100)
    assert len(chunks) == 2
    assert chunks[0] == (start, start + timedelta(days=99))
    assert chunks[1] == (start + timedelta(days=100), end)
    _assert_chunks_ok(chunks, start, end, 100)
