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
