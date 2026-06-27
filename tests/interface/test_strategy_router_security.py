from fastapi import Request
import pytest

import src.application.interface.api.strategy_router as strategy_router
from src.application.common.exceptions import AuthorizationError


class _DummyStrategyService:
    async def get_golden_cross_recommendations(self, **kwargs):
        return kwargs


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/strategies/universe/golden-cross-recommendations",
            "headers": [],
            "client": ("127.0.0.1", 12345),
        }
    )


@pytest.mark.asyncio
async def test_recommendation_get_financial_filter_requires_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def deny_admin(request: Request) -> str:
        _ = request
        raise AuthorizationError("denied")

    monkeypatch.setattr(strategy_router, "verify_admin_access", deny_admin)

    with pytest.raises(AuthorizationError):
        await strategy_router.golden_cross_recommendations(
            request=_request(),
            service=_DummyStrategyService(),
            apply_financial_filter=True,
        )


@pytest.mark.asyncio
async def test_recommendation_get_without_financial_filter_stays_public(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_if_admin_checked(request: Request) -> str:
        _ = request
        raise AssertionError("plain recommendation GET should not require admin")

    monkeypatch.setattr(strategy_router, "verify_admin_access", fail_if_admin_checked)

    response = await strategy_router.golden_cross_recommendations(
        request=_request(),
        service=_DummyStrategyService(),
        apply_financial_filter=False,
    )

    assert response.success is True
