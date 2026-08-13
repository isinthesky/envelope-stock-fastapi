# -*- coding: utf-8 -*-
"""공개 전략 포털(/page/*) 페이지 경계 테스트

- 세 공개 페이지가 비관리자 요청에서 200
- 사이드바에는 공개 메뉴 3개만 존재 (관리자 UI/링크 노출 금지)
- 폐기된 오늘의 추천 URL은 스캔 페이지로 영구 리다이렉트
- 공개 HTML에 관리자 CSRF 헤더/관리자 endpoint 문자열 없음
- 스캔 페이지에는 KOSPI/KOSDAQ/ETF 정적 option이 없고 로딩/비활성 상태로만 렌더링됨
  (실제 옵션은 capability API 응답에 따라 JS가 채운다 — 플랜 4.1/5단계)
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.interface.page.public_strategy_page_router import (
    router as public_strategy_page_router,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

PUBLIC_PAGES = {
    "/page/": "public_overview",
    "/page/scan/": "public_scan",
    "/page/sell-analysis/": "public_sell_analysis",
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


def test_public_sidebar_has_only_public_strategy_menu_items() -> None:
    client = TestClient(_build_app(), raise_server_exceptions=False)

    for path in PUBLIC_PAGES:
        html = client.get(path).text
        assert html.count("<li>") == 3, path
        assert 'href="/page/"' in html, path
        assert 'href="/page/scan/"' in html, path
        assert 'href="/page/sell-analysis/"' in html, path
        assert 'href="/page/recommendations/"' not in html, path
        assert "오늘의 추천" not in html, path
        assert "전략 인사이트" in html, path


def test_retired_recommendations_page_redirects_permanently_to_scan() -> None:
    client = TestClient(_build_app(), raise_server_exceptions=False)

    response = client.get("/page/recommendations/", follow_redirects=False)

    assert response.status_code == 308
    assert response.headers["location"] == "/page/scan/"


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


def test_public_overview_explains_buy_and_sell_strategies() -> None:
    client = TestClient(_build_app(), raise_server_exceptions=False)

    html = client.get("/page/").text

    assert "매수 전략 (골든크로스)" in html
    assert "매도 전략 (기술지표 종합)" in html
    assert "Stoch / RSI 70" in html
    assert "거래량·ADX" in html
    assert "보유 유지" in html
    assert "1차 비중축소" in html
    assert "2차 비중축소" in html
    assert "전량 매도 검토" in html
    assert 'href="/page/sell-analysis/"' in html
    assert "진입가·보유수량·개인수급 없이" in html


def test_public_overview_uses_canonical_buy_state_labels() -> None:
    client = TestClient(_build_app(), raise_server_exceptions=False)

    html = client.get("/page/").text

    assert 'K &lt; 30<br><small>매수 준비</small>' in html
    assert '회복 일부<br><small>매수 관심</small>' in html
    assert "최근 과매도 이후 K 상승 또는 K&gt;D" in html
    assert 'K &lt; 30<br><small>매수 관심</small>' not in html


# ==================== 스캔 페이지: capability 기반 렌더링 (플랜 4.1/5단계) ====================


def test_public_scan_page_has_no_static_kospi_kosdaq_options() -> None:
    """시장 select는 서버가 KOSPI/KOSDAQ/ETF/전체를 하드코딩하지 않는다.

    실제 가용 시장은 GET /api/v1/public/strategies/scan-capabilities 응답을 보고
    JS가 채운다 — 서버가 정적 option을 내려보내면 ETF 전용 운영에서도 KOSPI/KOSDAQ이
    선택 가능한 것처럼 보이는 회귀(플랜 2.3)가 재발한다.
    """
    client = TestClient(_build_app(), raise_server_exceptions=False)

    html = client.get("/page/scan/").text

    assert 'value="KOSPI"' not in html
    assert 'value="KOSDAQ"' not in html
    assert 'value="ETF"' not in html
    assert ">전체<" not in html


def test_public_scan_page_renders_loading_placeholder_and_disabled_controls() -> None:
    """초기 HTML은 로딩 placeholder 1개 option + 비활성 select/버튼 상태로 렌더링된다.

    JS 비활성 환경에서도 빈 시장 select가 실행 가능한 것처럼 보이지 않아야 한다.
    """
    client = TestClient(_build_app(), raise_server_exceptions=False)

    html = client.get("/page/scan/").text

    assert html.count("<option") == 1
    assert "불러오는 중" in html
    assert 'id="public-scan-market"' in html and "disabled" in html
    assert 'id="public-scan-run"' in html
    assert 'id="public-scan-market-badge"' in html


def test_public_scan_page_script_calls_scan_capabilities_endpoint() -> None:
    """페이지가 로드하는 JS가 실제로 scan-capabilities 엔드포인트를 호출하는지 정적으로 확인한다.

    브라우저 실행 인프라가 없으므로 DOM 동작을 Python에서 모사하지 않고,
    페이지가 참조하는 정적 JS 자산에 엔드포인트 문자열이 존재하는지만 검증한다(플랜 6.4).
    """
    client = TestClient(_build_app(), raise_server_exceptions=False)
    html = client.get("/page/scan/").text

    assert "public_strategy_scan.js" in html

    js_path = REPO_ROOT / "static" / "js" / "pages" / "public_strategy_scan.js"
    js_source = js_path.read_text(encoding="utf-8")
    assert "/api/v1/public/strategies/scan-capabilities" in js_source


def test_public_scan_page_groups_signals_and_declares_20_result_limit() -> None:
    client = TestClient(_build_app(), raise_server_exceptions=False)
    html = client.get("/page/scan/").text
    js_source = (REPO_ROOT / "static" / "js" / "pages" / "public_strategy_scan.js").read_text(
        encoding="utf-8"
    )

    assert "위 카드는 전체 스캔 집계" in html
    assert "최대 20개 종목만 표시" in html
    assert "신호 등급별 골든크로스 추천 종목" in html
    assert "MAX_DISPLAY_RESULTS = 20" in js_source
    assert "signal-group-row" in js_source
    assert 'emptyMessage = label + " 종목 없음"' in js_source
    assert 'id="stat-interest"' in html
    assert 'id="stat-ready"' in html
    assert 'setText("stat-interest", safeNum(data.buy_interest_count))' in js_source
    assert 'setText("stat-ready", safeNum(data.ready_to_buy_count))' in js_source
    assert 'candidateStates = ["OPTIMAL_BUY", "BUY_INTEREST", "READY_TO_BUY"]' in js_source
    assert "추천 우선순위 상위 20개 밖입니다" in js_source
    assert '"표시 " + safeNum(stocks.length) + " / 전체 " + safeNum(total)' in js_source
    assert "종목은 표시 순위 밖입니다" in js_source
    assert '"개 · 매수 관심 "' in js_source
    assert '"개 · 매수 준비 "' in js_source


def test_public_scan_page_persists_and_restores_recent_result_with_relative_time() -> None:
    client = TestClient(_build_app(), raise_server_exceptions=False)
    html = client.get("/page/scan/").text
    js_source = (REPO_ROOT / "static" / "js" / "pages" / "public_strategy_scan.js").read_text(
        encoding="utf-8"
    )

    assert 'id="public-scan-age"' in html
    assert 'id="public-scan-cache-badge"' in html
    assert "publicStrategyScanResult:v1" in js_source
    assert "window.localStorage.setItem" in js_source
    assert "window.localStorage.getItem" in js_source
    assert "renderResult(stored, { restored: true })" in js_source
    assert 'return minutes + "분 전"' in js_source
    assert 'return Math.floor(hours / 24) + "일 전"' in js_source


def test_public_sell_analysis_page_is_public_only_and_persistent() -> None:
    client = TestClient(_build_app(), raise_server_exceptions=False)
    html = client.get("/page/sell-analysis/").text
    js_source = (REPO_ROOT / "static" / "js" / "pages" / "public_sell_analysis.js").read_text(
        encoding="utf-8"
    )

    assert "public_sell_analysis.js" in html
    assert 'id="public-sell-form"' in html
    assert 'aria-live="polite"' in html
    assert "/api/v1/public/strategies/sell-analysis" in js_source
    assert 'id="public-sell-history-list"' in html
    assert 'id="public-sell-history-count"' in html
    assert "publicSellAnalysisHistory:v2" in js_source
    assert "publicSellAnalysisResult:v1" in js_source  # v1 단일 결과 migration
    assert "MAX_HISTORY_RESULTS = 20" in js_source
    assert "saveToHistory(lastResult)" in js_source
    assert "entry.symbol !== safe.symbol || entry.name" in js_source
    assert "renderHistory()" in js_source
    assert 'data-history-analyzed-at' not in html  # 이력은 안전한 DOM API로 동적 생성
    assert "window.localStorage.setItem" in js_source
    assert "window.localStorage.getItem" in js_source
    assert 'return minutes + "분 전"' in js_source
    assert 'return Math.floor(hours / 24) + "일 전"' in js_source

    combined = html + js_source
    for marker in [
        "/api/v1/strategies/",
        "analysis-history",
        "strategy_id",
        "entry_price",
        "holding_quantity",
        "cash-plan",
        "backtest",
    ]:
        assert marker not in combined
