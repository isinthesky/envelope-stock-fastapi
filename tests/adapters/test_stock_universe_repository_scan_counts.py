# -*- coding: utf-8 -*-
"""StockUniverseRepository.get_scan_market_counts 테스트

공개 스캔 시장 가용성 판정(`.omo/plans/public-scan-market-availability.md` 6.1)이
`get_scan_stocks()`와 동일한 조건(is_active/is_tradable/is_excluded)으로 시장별
활성 종목 수를 집계하는지 검증한다.

실 DB(docker postgres)를 사용하지 않고, session.execute를 mock으로 대체해 실제로
구성된 SQL 구문(WHERE/GROUP BY)을 검사하는 방식으로 필터 조건을 검증한다
(tests/domain/test_analysis_history_repository.py의 fake session 패턴을 따름).
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.adapters.database.models.stock_universe import MarketType
from src.adapters.database.repositories.stock_universe_repository import (
    StockUniverseRepository,
)

# get_scan_stocks()와 공유해야 하는 조건 (활성/거래가능/미제외)
_SHARED_CONDITIONS = {
    "stock_universe.is_active = true",
    "stock_universe.is_tradable = true",
    "stock_universe.is_excluded = false",
}


def _compiled_sql(stmt) -> str:
    """literal_binds로 컴파일해 조건절을 문자열로 검사한다 (실 DB 연결 없이 SQL 구조만 검증)."""
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


def _mock_count_session(rows: list[tuple]) -> MagicMock:
    """get_scan_market_counts용 mock 세션: execute() 결과의 .all()이 (market, count) 튜플을 반환"""
    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=rows)))
    return session


def _mock_scalars_session(rows: list) -> MagicMock:
    """get_scan_stocks용 mock 세션: execute() 결과의 .scalars().all()이 row 목록을 반환"""
    session = MagicMock()
    session.execute = AsyncMock(
        return_value=MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=rows)))
        )
    )
    return session


# ==================== 조건절 구성 ====================


@pytest.mark.asyncio
async def test_counts_apply_active_tradable_excluded_conditions() -> None:
    session = _mock_count_session([("ETF", 221)])
    repo = StockUniverseRepository()

    await repo.get_scan_market_counts([MarketType.ETF], session=session)

    stmt = session.execute.call_args.args[0]
    sql = _compiled_sql(stmt)
    for predicate in _SHARED_CONDITIONS:
        assert predicate in sql
    assert "stock_universe.market IN ('ETF')" in sql
    assert "GROUP BY stock_universe.market" in sql


@pytest.mark.asyncio
async def test_counts_do_not_apply_screening_conditions() -> None:
    """시가총액/스크리닝 통과 조건은 반영하지 않는다 (get_eligible_stocks와 달리 실제
    공개 스캔(get_scan_stocks) 대상 조건과 정확히 일치해야 하므로)."""
    session = _mock_count_session([("KOSPI", 10)])
    repo = StockUniverseRepository()

    await repo.get_scan_market_counts([MarketType.KOSPI], session=session)

    sql = _compiled_sql(session.execute.call_args.args[0])
    assert "passed_market_cap" not in sql
    assert "passed_volume" not in sql
    assert "screening_score" not in sql


@pytest.mark.asyncio
async def test_counts_conditions_match_get_scan_stocks_base_condition() -> None:
    """활성/거래가능/미제외 조건 텍스트가 get_scan_stocks()가 사용하는 조건과 동일하다."""
    repo = StockUniverseRepository()

    counts_session = _mock_count_session([])
    await repo.get_scan_market_counts([MarketType.KOSPI], session=counts_session)
    counts_sql = _compiled_sql(counts_session.execute.call_args.args[0])

    scan_session = _mock_scalars_session([])
    await repo.get_scan_stocks(market=MarketType.KOSPI, session=scan_session)
    scan_sql = _compiled_sql(scan_session.execute.call_args.args[0])

    for predicate in _SHARED_CONDITIONS:
        assert predicate in counts_sql
        assert predicate in scan_sql


# ==================== 집계 결과 매핑 ====================


@pytest.mark.asyncio
async def test_markets_with_no_active_rows_are_zero_filled() -> None:
    """inactive/거래불가/excluded로 필터링돼 행이 0개인 시장은 결과에서 0으로 해석된다."""
    # KOSPI/KOSDAQ은 활성 행이 없어 GROUP BY 결과에 포함되지 않는 상황을 시뮬레이션
    session = _mock_count_session([("ETF", 221)])
    repo = StockUniverseRepository()

    result = await repo.get_scan_market_counts(
        [MarketType.KOSPI, MarketType.KOSDAQ, MarketType.ETF], session=session
    )

    assert result == {"KOSPI": 0, "KOSDAQ": 0, "ETF": 221}


@pytest.mark.asyncio
async def test_empty_markets_list_returns_empty_dict_without_query() -> None:
    session = _mock_count_session([])
    repo = StockUniverseRepository()

    result = await repo.get_scan_market_counts([], session=session)

    assert result == {}
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_counts_are_coerced_to_int() -> None:
    """DB 드라이버가 int가 아닌 수치 타입(Decimal 등)을 반환해도 int로 강제 변환된다."""
    session = _mock_count_session([("KOSPI", Decimal("5"))])
    repo = StockUniverseRepository()

    result = await repo.get_scan_market_counts([MarketType.KOSPI], session=session)

    assert result == {"KOSPI": 5}
    assert isinstance(result["KOSPI"], int)


@pytest.mark.asyncio
async def test_only_requested_markets_are_queried() -> None:
    session = _mock_count_session([("KOSPI", 3), ("KOSDAQ", 2)])
    repo = StockUniverseRepository()

    await repo.get_scan_market_counts([MarketType.KOSPI, MarketType.KOSDAQ], session=session)

    sql = _compiled_sql(session.execute.call_args.args[0])
    assert "stock_universe.market IN ('KOSPI', 'KOSDAQ')" in sql
    assert "'ETF'" not in sql
