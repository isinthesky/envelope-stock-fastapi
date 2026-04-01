from src.adapters.external.kofia_client import KofiaClient


def test_market_credit_trend_marks_overheated_when_multiple_conditions_match() -> None:
    client = KofiaClient()

    rows = {
        "ds1": [
            {"TMPV1": "20260401", "TMPV2": "전체", "TMPV3": 74955524, "TMPV5": 3181603332},
            {"TMPV1": "20260331", "TMPV2": "전체", "TMPV3": 39743233, "TMPV5": 3145131365},
            {"TMPV1": "20260330", "TMPV2": "전체", "TMPV3": 78879452, "TMPV5": 3147221427},
            {"TMPV1": "20260327", "TMPV2": "전체", "TMPV3": 53666160, "TMPV5": 3175934202},
            {"TMPV1": "20260326", "TMPV2": "전체", "TMPV3": 57277333, "TMPV5": 3168004093},
        ]
    }

    async def fake_post_json(payload):
        return rows

    client._post_json = fake_post_json  # type: ignore[attr-defined]

    import asyncio

    result = asyncio.run(client.get_market_credit_trend("20260101", "20260401", "전체"))

    assert result is not None
    assert result.is_overheated is True
    assert len(result.reasons) >= 2


def test_market_credit_trend_falls_back_to_total_when_market_specific_rows_missing() -> None:
    client = KofiaClient()

    rows = {
        "ds1": [
            {"TMPV1": "20260401", "TMPV2": "전체", "TMPV3": 74955524, "TMPV5": 3181603332},
            {"TMPV1": "20260331", "TMPV2": "전체", "TMPV3": 39743233, "TMPV5": 3145131365},
        ]
    }

    async def fake_post_json(payload):
        return rows

    client._post_json = fake_post_json  # type: ignore[attr-defined]

    import asyncio

    result = asyncio.run(client.get_market_credit_trend("20260101", "20260401", "유가증권"))

    assert result is not None
    assert result.market_label == "전체"
