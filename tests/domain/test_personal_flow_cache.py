from src.adapters.external.naver.stock_client import NaverStockClient


def test_personal_flow_uses_cached_rows_without_fetch() -> None:
    client = NaverStockClient()

    cached_rows = [
        {"bizdate": "20260401", "individualPureBuyQuant": 100, "closePrice": 1000, "accumulatedTradingVolume": 1000},
        {"bizdate": "20260331", "individualPureBuyQuant": 90, "closePrice": 990, "accumulatedTradingVolume": 900},
        {"bizdate": "20260330", "individualPureBuyQuant": 80, "closePrice": 980, "accumulatedTradingVolume": 800},
        {"bizdate": "20260327", "individualPureBuyQuant": 70, "closePrice": 970, "accumulatedTradingVolume": 700},
        {"bizdate": "20260326", "individualPureBuyQuant": 60, "closePrice": 960, "accumulatedTradingVolume": 600},
    ]

    async def fake_load(symbol: str):
        return cached_rows

    async def fail_fetch(symbol: str):
        raise AssertionError("fetch should not be called when cache is warm")

    client._load_recent_cached_personal_flow = fake_load  # type: ignore[attr-defined]
    client._fetch_and_cache_personal_flow = fail_fetch  # type: ignore[attr-defined]

    import asyncio

    result = asyncio.run(client.get_personal_flow_data("005930"))

    assert result is not None
    assert result.latest_date == "20260401"
    assert result.recent_5d_net_buy == 400
