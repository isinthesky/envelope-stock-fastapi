import asyncio

from src.adapters.external.kofia_client import KofiaClient
from src.adapters.external.naver.stock_client import NaverStockClient
from src.application.domain.strategy.sell_risk_backfill_service import (
    SellRiskBackfillService,
)


def test_resolve_symbols_filters_invalid_explicit_input() -> None:
    # 명시적 symbols 인자도 형식 검증을 우회하지 않아야 한다 (메모 행 차단 + strip 정규화)
    service = SellRiskBackfillService(session=None)

    resolved = asyncio.run(
        service.resolve_symbols(["005930", "MEMO-BROADCAST-1", " 000660 "])
    )

    assert [row["symbol"] for row in resolved] == ["005930", "000660"]


def test_resolve_symbols_all_invalid_explicit_input_returns_empty() -> None:
    service = SellRiskBackfillService(session=None)

    resolved = asyncio.run(service.resolve_symbols(["MEMO-BROADCAST-1", "HALLOWEEN-STRAT"]))

    assert resolved == []


def test_market_credit_backfill_chunks_two_year_range() -> None:
    client = KofiaClient()
    calls: list[tuple[str, str]] = []

    async def fake_fetch(start_date: str, end_date: str) -> dict[str, int]:
        calls.append((start_date, end_date))
        return {"전체": 3, "유가증권": 2}

    client._fetch_and_cache_snapshots = fake_fetch  # type: ignore[attr-defined]

    result = asyncio.run(client.refresh_market_credit_cache("20240101", "20250131"))

    assert len(calls) >= 2
    assert result["전체"] == len(calls) * 3
    assert result["유가증권"] == len(calls) * 2


def test_personal_flow_backfill_counts_only_requested_range() -> None:
    client = NaverStockClient()

    async def fake_fetch(symbol: str, size: int | None = None) -> list[dict]:
        _ = symbol, size
        return [
            {"bizdate": "20250105", "individualPureBuyQuant": 100},
            {"bizdate": "20250104", "individualPureBuyQuant": 90},
            {"bizdate": "20230103", "individualPureBuyQuant": 80},
        ]

    client._fetch_and_cache_personal_flow = fake_fetch  # type: ignore[attr-defined]

    result = asyncio.run(
        client.backfill_personal_flow_cache(
            symbol="005930",
            years=1,
            end_date="20250105",
        )
    )

    assert result["symbol"] == "005930"
    assert result["rows"] == 2
