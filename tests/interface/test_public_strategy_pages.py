# -*- coding: utf-8 -*-
"""공개 전략 포털(/page/*) 페이지 경계 테스트

- 세 공개 페이지가 비관리자 요청에서 200
- 사이드바에는 공개 메뉴 3개만 존재 (관리자 UI/링크 노출 금지)
- 공개 HTML에 관리자 CSRF 헤더/관리자 endpoint 문자열 없음
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.interface.page.public_strategy_page_router import (
    router as public_strategy_page_router,
)

PUBLIC_PAGES = {
    "/page/": "public_overview",
    "/page/scan/": "public_scan",
    "/page/recommendations/": "public_recommendations",
}

# 공개 화면에 노출되어서는 안 되는 관리자 흔적
FORBIDDEN_MARKERS = [
    "/mypage/",
    "/ops/",
    "Account",
    "Order",
    "Access Logs",
    "X-Requested-With",
    "XMLHttpRequest",
    "analysis-history",
    "universe/refresh",
    "financial-filter",
    "/api/v1/strategies/",
]


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(public_strategy_page_router)
    return app


def test_public_pages_render_for_anonymous_visitors() -> None:
    client = TestClient(_build_app(), raise_server_exceptions=False)

    for path in PUBLIC_PAGES:
        response = client.get(path)
        assert response.status_code == 200, path


def test_public_sidebar_has_exactly_three_menu_items() -> None:
    client = TestClient(_build_app(), raise_server_exceptions=False)

    for path in PUBLIC_PAGES:
        html = client.get(path).text
        assert html.count("<li>") == 3, path
        assert 'href="/page/"' in html, path
        assert 'href="/page/scan/"' in html, path
        assert 'href="/page/recommendations/"' in html, path
        assert "전략 인사이트" in html, path


def test_public_pages_mark_active_menu_with_aria_current() -> None:
    client = TestClient(_build_app(), raise_server_exceptions=False)

    for path in PUBLIC_PAGES:
        html = client.get(path).text
        assert html.count('aria-current="page"') == 1, path


def test_public_pages_do_not_leak_admin_ui_or_endpoints() -> None:
    client = TestClient(_build_app(), raise_server_exceptions=False)

    for path in PUBLIC_PAGES:
        html = client.get(path).text
        for marker in FORBIDDEN_MARKERS:
            assert marker not in html, f"{path} leaks {marker!r}"


def test_public_pages_show_disclaimer_footer() -> None:
    client = TestClient(_build_app(), raise_server_exceptions=False)

    for path in PUBLIC_PAGES:
        html = client.get(path).text
        assert "투자 조언이 아니며" in html, path


def test_public_layout_uses_isolated_sidebar_storage_key() -> None:
    client = TestClient(_build_app(), raise_server_exceptions=False)

    html = client.get("/page/").text
    assert "publicStrategySidebarHidden" in html
    # 관리자 레이아웃의 sidebarHidden 키를 그대로 쓰지 않는다
    assert '"sidebarHidden"' not in html
