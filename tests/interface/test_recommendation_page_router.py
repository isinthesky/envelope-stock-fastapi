from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.interface.page.recommendation_page_router import router


app = FastAPI()
app.include_router(router)
client = TestClient(app)


def test_recommendation_page_renders_without_error() -> None:
    response = client.get("/mypage/recommendation/")

    assert response.status_code == 200
    assert "Recommendation - Stock API Admin" in response.text
    assert "추천 후보 및 룰셋" in response.text
    assert "/static/js/pages/recommendation.js" in response.text
    assert 'option value="excess_return"' in response.text
    assert 'option value="mdd"' not in response.text
    assert 'option value="turnover"' not in response.text
