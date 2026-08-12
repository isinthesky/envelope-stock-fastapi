# -*- coding: utf-8 -*-
"""기존 /api/v1/strategies/* 범용 API의 관리자 보호 경계 테스트

main.py와 동일하게 라우터 단위 verify_admin_access를 적용해 검증한다.
외부 사용자는 새 공개 API(/api/v1/public/strategies/*)만 이용해야 한다.
"""

from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from src.application.common.dependencies import verify_admin_access
from src.application.interface.api.strategy_router import router as strategy_router
from src.settings.exception_handlers import register_exception_handlers


async def _allow_admin_access(request: Request) -> str:
    return "127.0.0.1"


def _app_like_main() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(
        strategy_router,
        prefix="/api/v1/strategies",
        dependencies=[Depends(verify_admin_access)],
    )
    return app


def test_non_admin_is_denied_on_strategy_read_apis() -> None:
    client = TestClient(_app_like_main(), raise_server_exceptions=False)

    denied_paths = [
        "/api/v1/strategies/universe",
        "/api/v1/strategies/universe/golden-cross-scan",
        "/api/v1/strategies/universe/golden-cross-recommendations",
        "/api/v1/strategies/analysis-history?analysis_type=buy",
        "/api/v1/strategies/presets",
        "/api/v1/strategies/scheduler/status",
    ]
    for path in denied_paths:
        response = client.get(path)
        assert response.status_code == 403, path
        assert response.json()["error"]["code"] == "AUTHORIZATION_ERROR", path


def test_non_admin_is_denied_on_strategy_write_apis() -> None:
    client = TestClient(_app_like_main(), raise_server_exceptions=False)

    response = client.post(
        "/api/v1/strategies/universe/refresh",
        headers={"x-requested-with": "XMLHttpRequest"},
    )
    assert response.status_code == 403

    response = client.post(
        "/api/v1/strategies/1/execute",
        json={"dry_run": True},
        headers={"x-requested-with": "XMLHttpRequest"},
    )
    assert response.status_code == 403


def test_forged_forwarded_header_does_not_bypass_admin_gate() -> None:
    client = TestClient(_app_like_main(), raise_server_exceptions=False)

    response = client.get(
        "/api/v1/strategies/universe",
        headers={"X-Forwarded-For": "127.0.0.1", "X-Real-IP": "127.0.0.1"},
    )

    assert response.status_code == 403


def test_admin_override_allows_strategy_api() -> None:
    app = _app_like_main()
    app.dependency_overrides[verify_admin_access] = _allow_admin_access
    try:
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/v1/strategies/presets")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["success"] is True
