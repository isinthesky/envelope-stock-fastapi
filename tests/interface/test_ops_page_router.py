from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from src.application.common.dependencies import verify_admin_access
from src.application.interface.page.ops_page_router import router
from src.settings.exception_handlers import register_exception_handlers


app = FastAPI()
register_exception_handlers(app)
app.include_router(router)


async def _allow_admin_access(request: Request) -> str:
    return "127.0.0.1"


def test_ops_page_requires_admin_dependency_override() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/ops/")
    assert response.status_code >= 400


def test_ops_page_renders_when_admin_dependency_is_allowed() -> None:
    app.dependency_overrides[verify_admin_access] = _allow_admin_access
    try:
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/ops/")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert "Operations Dashboard" in response.text
    assert "/api/v1/ops" in response.text
    assert "const esc = (value)" in response.text
    assert "esc(err.message)" in response.text
