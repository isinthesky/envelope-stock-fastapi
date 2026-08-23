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
