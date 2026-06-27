import asyncio

from src.adapters.external.kofia_client import KofiaClient


class _DummyResponse:
    def raise_for_status(self) -> None:
        return None


class _DummyAsyncClient:
    def __init__(self, *args, **kwargs) -> None:
        self.get_calls: list[str] = []

    async def get(self, url: str) -> _DummyResponse:
        self.get_calls.append(url)
        return _DummyResponse()

    async def aclose(self) -> None:
        return None


def test_resolve_unit_value_uses_basic_unit_metadata() -> None:
    resolved = KofiaClient._resolve_unit_value(
        "T2050^06",
        [
            {"GROUP_CD": "T2050", "COMMON_CD": "05", "CODE_ENGNM": "100000"},
            {"GROUP_CD": "T2050", "COMMON_CD": "06", "CODE_ENGNM": "1000000"},
        ],
    )

    assert resolved == "1000000"


def test_prime_service_page_initializes_client_without_deadlock(monkeypatch) -> None:
    created_clients: list[_DummyAsyncClient] = []

    def fake_async_client(*args, **kwargs):
        client = _DummyAsyncClient(*args, **kwargs)
        created_clients.append(client)
        return client

    monkeypatch.setattr("src.adapters.external.kofia_client.httpx.AsyncClient", fake_async_client)

    client = KofiaClient()
    page_url = asyncio.run(
        asyncio.wait_for(client._prime_service_page("STATSCU0100000070"), timeout=0.2)
    )

    assert page_url.endswith("serviceId=STATSCU0100000070")
    assert created_clients[0].get_calls == [page_url]
    asyncio.run(client.aclose())


def test_build_market_credit_snapshots_maps_0070_columns_to_markets() -> None:
    snapshots = KofiaClient._build_market_credit_snapshots(
        [
            {
                "TMPV1": "20260423",
                "TMPV2": 35079918,
                "TMPV3": 24243090,
                "TMPV4": 10836828,
                "TMPV5": 49415,
                "TMPV6": 43469,
                "TMPV7": 5947,
            }
        ]
    )

    assert snapshots == [
        {
            "market_label": "전체",
            "biz_date": "20260423",
            "trading_volume": None,
            "balance_million": 35079918,
            "short_balance_million": 49415,
        },
        {
            "market_label": "유가증권",
            "biz_date": "20260423",
            "trading_volume": None,
            "balance_million": 24243090,
            "short_balance_million": 43469,
        },
        {
            "market_label": "코스닥",
            "biz_date": "20260423",
            "trading_volume": None,
            "balance_million": 10836828,
            "short_balance_million": 5947,
        },
    ]


def test_market_credit_trend_marks_overheated_when_multiple_conditions_match() -> None:
    client = KofiaClient()

    rows = [
        {"TMPV1": "20260401", "TMPV2": "전체", "TMPV3": None, "TMPV5": 3181603332},
        {"TMPV1": "20260331", "TMPV2": "전체", "TMPV3": None, "TMPV5": 3145131365},
        {"TMPV1": "20260330", "TMPV2": "전체", "TMPV3": None, "TMPV5": 3147221427},
        {"TMPV1": "20260327", "TMPV2": "전체", "TMPV3": None, "TMPV5": 3175934202},
        {"TMPV1": "20260326", "TMPV2": "전체", "TMPV3": None, "TMPV5": 3168004093},
    ]

    async def fake_load_recent_rows(market_label):
        return rows if market_label == "전체" else []

    client._load_recent_rows = fake_load_recent_rows  # type: ignore[attr-defined]

    result = asyncio.run(client.get_market_credit_trend("20260101", "20260401", "전체"))

    assert result is not None
    assert result.is_overheated is True
    assert len(result.reasons) >= 2


def test_market_credit_trend_falls_back_to_total_when_market_specific_rows_missing() -> None:
    client = KofiaClient()

    rows = [
        {"TMPV1": "20260401", "TMPV2": "전체", "TMPV3": None, "TMPV5": 3181603332},
        {"TMPV1": "20260331", "TMPV2": "전체", "TMPV3": None, "TMPV5": 3145131365},
    ]

    async def fake_load_recent_rows(market_label):
        return rows if market_label == "전체" else []

    async def fake_fetch_and_cache(start_date, end_date):
        return {"전체": rows}

    client._load_recent_rows = fake_load_recent_rows  # type: ignore[attr-defined]
    client._fetch_and_cache_snapshots = fake_fetch_and_cache  # type: ignore[attr-defined]

    result = asyncio.run(client.get_market_credit_trend("20260101", "20260401", "유가증권"))

    assert result is not None
    assert result.market_label == "전체"


def test_market_credit_skips_fetch_when_cache_is_fresh() -> None:
    client = KofiaClient()
    rows = [
        {"TMPV1": "20260401", "TMPV2": "전체", "TMPV3": None, "TMPV5": 3181603332},
        {"TMPV1": "20260331", "TMPV2": "전체", "TMPV3": None, "TMPV5": 3145131365},
    ]

    async def fake_load_recent_rows(market_label):
        return rows

    async def fail_fetch(start_date, end_date):
        raise AssertionError("fetch should not be called when cache is fresh")

    client._load_recent_rows = fake_load_recent_rows  # type: ignore[attr-defined]
    client._fetch_and_cache_snapshots = fail_fetch  # type: ignore[attr-defined]

    result = asyncio.run(client.get_market_credit_trend("20260101", "20260401", "전체"))

    assert result is not None
    assert result.latest_date == "20260401"
