from fastapi.testclient import TestClient

from src.application.common.dependencies import ADMIN_SESSION_COOKIE, get_admin_auth_service
from src.main import app


class _AlwaysLoggedIn:
    async def get_session(self, token: str) -> object:
        return object()


def test_api_documentation_routes_are_disabled_in_all_environments() -> None:
    """Keep the documented no-exposure policy aligned with the FastAPI configuration."""
    assert app.docs_url is None
    assert app.redoc_url is None
    assert app.openapi_url is None

    async def _service() -> _AlwaysLoggedIn:
        return _AlwaysLoggedIn()

    # 로그인 게이트를 통과한 상태에서도 문서 경로는 존재하지 않아야 한다.
    app.dependency_overrides[get_admin_auth_service] = _service
    try:
        client = TestClient(app)
        client.cookies.set(ADMIN_SESSION_COOKIE, "any")
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert client.get(path).status_code == 404
    finally:
        app.dependency_overrides.clear()
