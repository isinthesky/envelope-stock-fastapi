# -*- coding: utf-8 -*-
"""관리자 페이지 엔진 출처 배지 회귀 테스트

매도 판단 엔진은 서로 규칙이 다른 3벌이다.
- E1: 월~금 15:35 실주문 FSM (내 전략 화면에서 활성화한 전략만)
- E2: 화면·API·텔레그램 전용 매도 분석 (주문 없음)
- E3: 백테스트 전용 규칙 (E1/E2 어느 쪽도 아님)

기존 테스트 파일이 없던 holdings / backtest / strategy_dashboard / recommendation /
ops 화면의 배지가 조용히 사라지지 않도록 고정한다.
"""

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from src.application.common.dependencies import verify_admin_access
from src.application.interface.page.backtest_page_router import router as backtest_router
from src.application.interface.page.holdings_page_router import router as holdings_router
from src.application.interface.page.ops_page_router import router as ops_router
from src.application.interface.page.recommendation_page_router import (
    router as recommendation_router,
)
from src.application.interface.page.strategy_dashboard_page_router import (
    router as strategy_dashboard_router,
)
from src.settings.config import settings


def _client(*routers) -> TestClient:
    app = FastAPI()
    for router in routers:
        app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def test_holdings_page_labels_analysis_engine_not_live_order() -> None:
    html = _client(holdings_router).get("/mypage/holdings/").text

    assert "분석 엔진 E2" in html
    assert "분석 결과일 뿐 실주문이 아닙니다" in html


def test_backtest_page_labels_backtest_engine_differs_from_live_rules() -> None:
    html = _client(backtest_router).get("/mypage/backtest/").text

    assert "백테스트 엔진 E3" in html
    assert "실주문 규칙(E1)과 다릅니다" in html


def test_recommendation_page_marks_walk_forward_as_e1_measurement() -> None:
    html = _client(recommendation_router).get("/mypage/recommendation/").text

    assert "실주문 엔진 E1 측정" in html


def test_strategy_dashboard_shows_live_trading_switch_state(monkeypatch) -> None:
    """실주문 kill-switch 문구가 GoldenCrossEngine.execute의 실제 거동과 일치해야 한다.

    OFF일 때 엔진(golden_cross_engine.py:137)은 dry-run으로 강등해 재실행하는 것이 아니라
    주문 없이 에러만 담아 즉시 반환한다. 따라서 신호도 0건이다.
    """
    monkeypatch.setattr(settings, "strategy_live_trading_enabled", False)
    html_off = _client(strategy_dashboard_router).get("/mypage/strategy/dashboard").text

    assert "실주문 엔진 E1" in html_off
    assert "실주문 스위치 OFF" in html_off
    assert "실계좌 주문을 냅니다" not in html_off
    # dry-run 대체 실행이라는 잘못된 안내가 되살아나지 않도록 고정한다.
    assert "dry-run으로만 처리됩니다" not in html_off
    assert "자동 실행이 차단됩니다" in html_off
    assert "dry-run으로 대체되지 않습니다" in html_off
    assert "신호가 하나도 생성되지 않습니다" in html_off

    monkeypatch.setattr(settings, "strategy_live_trading_enabled", True)
    html_on = _client(strategy_dashboard_router).get("/mypage/strategy/dashboard").text

    assert "실주문 스위치 ON" in html_on
    assert "실계좌 주문을 냅니다" in html_on


def test_strategy_dashboard_limits_kill_switch_scope_to_scheduled_execution(
    monkeypatch,
) -> None:
    """kill-switch가 서버 전체 주문 차단기라는 오해를 주지 않아야 한다.

    이 스위치를 참조하는 지점은 golden_cross_engine.py:137 한 곳이며,
    POST /api/v1/orders(order_router → OrderService.create_order)는 이를 거치지 않는다.
    """
    for enabled in (False, True):
        monkeypatch.setattr(settings, "strategy_live_trading_enabled", enabled)
        html = _client(strategy_dashboard_router).get("/mypage/strategy/dashboard").text

        assert "전략 자동 실행 경로에만 적용되는 차단기" in html
        assert "POST /api/v1/orders 수동 주문은 이 스위치를 거치지 않습니다" in html
        assert "현재 주문이 나가지 않습니다" not in html


def test_ops_sell_watchlist_card_labels_analysis_engine() -> None:
    """운영 대시보드의 '매도 감시' 카드도 E2 산출물임을 밝힌다."""
    app = FastAPI()
    app.include_router(ops_router)

    async def _allow_admin_access(request: Request) -> str:
        return "127.0.0.1"

    app.dependency_overrides[verify_admin_access] = _allow_admin_access
    try:
        html = TestClient(app, raise_server_exceptions=False).get("/ops/").text
    finally:
        app.dependency_overrides.clear()

    assert "분석 엔진 E2" in html
    assert "이 카드가 주문을 내지는 않습니다" in html
