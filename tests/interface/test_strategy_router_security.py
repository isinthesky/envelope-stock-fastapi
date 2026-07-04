from fastapi import HTTPException, Request
import pytest

import src.application.interface.api.sell_rule_research_router as sell_rule_research_router
import src.application.interface.api.strategy_router as strategy_router
from src.application.common.exceptions import AuthorizationError


class _DummyStrategyService:
    async def get_golden_cross_recommendations(self, **kwargs):
        return kwargs


class _DummySellRuleResearchService:
    def __init__(self, session) -> None:
        self.session = session

    async def research_preregistered_sell_rules(
        self,
        config,
    ) -> dict:
        window = config.candidates[0].evaluation_window
        return {
            "symbols": list(config.symbols or []),
            "start_date": window.train_start_date,
            "end_date": window.test_end_date,
            "candidate_count": len(config.candidates),
            "service_session": self.session,
        }


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


@pytest.mark.asyncio
async def test_preregistered_sell_rule_research_forwards_query_to_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sell_rule_research_router,
        "SellPeakRuleResearchService",
        _DummySellRuleResearchService,
    )

    response = await sell_rule_research_router.research_preregistered_sell_rules(
        admin_access="127.0.0.1",
        session="db-session",
        symbols="005930, 000660",
        start_date="20240101",
        end_date="20241231",
    )

    assert response.success is True
    assert response.data == {
        "symbols": ["005930", "000660"],
        "start_date": "20240101",
        "end_date": "20241231",
        "candidate_count": 2,
        "service_session": "db-session",
    }


@pytest.mark.asyncio
async def test_preregistered_sell_rule_research_rejects_short_range() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await sell_rule_research_router.research_preregistered_sell_rules(
            admin_access="127.0.0.1",
            session="db-session",
            symbols="005930",
            start_date="20240101",
            end_date="20240104",
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "date range must be at least 4 days"
