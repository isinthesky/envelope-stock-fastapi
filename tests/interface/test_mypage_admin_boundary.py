from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from src.application.common.dependencies import verify_admin_access
from src.application.interface.page.sell_strategy_page_router import router as sell_strategy_router
from src.application.interface.page.public_strategy_page_router import (
    router as public_strategy_router,
)
from src.settings.exception_handlers import register_exception_handlers


async def _allow_admin_access(request: Request) -> str:
    return "127.0.0.1"


def _app_with_admin_page_router() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(sell_strategy_router, dependencies=[Depends(verify_admin_access)])
    return app


def test_mypage_router_is_admin_gated_when_included_like_main() -> None:
    app = _app_with_admin_page_router()
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/mypage/sell-strategy/")

    assert response.status_code >= 400


def test_mypage_router_renders_for_allowed_admin_and_injects_csrf_fetch_guard() -> None:
    app = _app_with_admin_page_router()
    app.dependency_overrides[verify_admin_access] = _allow_admin_access
    try:
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/mypage/sell-strategy/")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert "Sell Strategy - Stock API Admin" in response.text
    assert "X-Requested-With" in response.text
    assert "XMLHttpRequest" in response.text


def test_public_page_does_not_mint_admin_csrf_header() -> None:
    app = FastAPI()
    app.include_router(public_strategy_router)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/page/")

    assert response.status_code == 200
    assert "X-Requested-With" not in response.text
    assert "XMLHttpRequest" not in response.text
