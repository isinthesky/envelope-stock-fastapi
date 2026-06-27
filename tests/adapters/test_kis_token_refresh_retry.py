import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock

from src.adapters.external.kis_api.client import KISAPIClient
from src.adapters.external.kis_api.exceptions import KISAPIError


@pytest.mark.asyncio
async def test_should_retry_with_token_refresh_for_expired_token_error() -> None:
    client = KISAPIClient()
    error = KISAPIError(
        message="KIS API Error: 기간이 만료된 token 입니다.",
        error_code="EGW00123",
        response_data={"msg_cd": "EGW00123", "msg1": "기간이 만료된 token 입니다."},
    )

    assert client._should_retry_with_token_refresh(error, attempt=0) is True
    assert client._should_retry_with_token_refresh(error, attempt=1) is False


@pytest.mark.asyncio
async def test_post_can_disable_transport_retry_for_non_idempotent_orders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = KISAPIClient()
    client.auth = MagicMock()
    client.auth.get_auth_headers = AsyncMock(return_value={})

    class TimeoutHTTPClient:
        def __init__(self) -> None:
            self.calls = 0

        async def post(self, *args, **kwargs):
            _ = args, kwargs
            self.calls += 1
            raise httpx.TimeoutException("ambiguous timeout")

    http_client = TimeoutHTTPClient()
    monkeypatch.setattr(client, "_get_client", AsyncMock(return_value=http_client))

    with pytest.raises(KISAPIError) as exc_info:
        await client.post(
            "/uapi/domestic-stock/v1/trading/order-cash",
            json={"PDNO": "005930"},
            retry_transport_errors=False,
        )

    assert exc_info.value.error_code == "POST_OUTCOME_UNKNOWN"
    assert http_client.calls == 1
