# -*- coding: utf-8 -*-
"""
Market Data Page Router - 시세 데이터 페이지
"""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(
    prefix="/mypage/market-data", tags=["MyPage-MarketData"], include_in_schema=False
)


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def market_data_page(request: Request) -> HTMLResponse:
    """시세 데이터 페이지"""
    return templates.TemplateResponse(
        "page/market_data.html", {"request": request, "active_page": "market_data"}
    )
