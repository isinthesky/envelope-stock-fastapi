from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.interface.page.sell_strategy_page_router import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)


def test_sell_strategy_page_renders_without_error() -> None:
    response = client.get("/mypage/sell-strategy/")

    assert response.status_code == 200
    assert "Sell Strategy - Stock API Admin" in response.text
    assert "매도 전략 분석" in response.text


def test_sell_strategy_assets_distinguish_insufficient_data_from_hold() -> None:
    project_root = Path(__file__).resolve().parents[2]
    script = (project_root / "static/js/pages/sell_strategy.js").read_text()
    styles = (project_root / "static/styles/sell_strategy.css").read_text()

    assert "INSUFFICIENT_DATA: '데이터 부족'" in script
    assert "stage-INSUFFICIENT_DATA" in styles


def test_sell_strategy_page_labels_each_engine_source() -> None:
    """매도 엔진 3벌(E1/E2/E3)의 출처가 화면에서 구분되어야 한다."""
    html = client.get("/mypage/sell-strategy/").text

    # 종목 분석 / 현금화 계획 = E2 (실주문 아님)
    assert "분석 엔진 E2" in html
    assert "이 화면의 어떤 버튼도 실주문을 내지 않습니다" in html
    # 유니버스 백테스트 = E3 (실주문 규칙과 다름)
    assert "백테스트 엔진 E3" in html
    assert "실주문 규칙(E1)과도, 위 매도 분석(E2)과도 다릅니다" in html
    # walk-forward 리포트 = E1 측정
    assert "실주문 엔진 E1 측정" in html


def test_admin_stylesheet_defines_engine_badge_classes() -> None:
    project_root = Path(__file__).resolve().parents[2]
    styles = (project_root / "static/styles/mypage.css").read_text(encoding="utf-8")

    for selector in ("p.engine-note", ".engine-badge", ".engine-e1", ".engine-e2", ".engine-e3"):
        assert selector in styles, selector
