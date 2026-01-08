# -*- coding: utf-8 -*-
"""
Sell Strategy Page Router - 매도 전략 페이지 라우터
"""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(prefix="/page/sell-strategy", tags=["Page-SellStrategy"], include_in_schema=False)


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def sell_strategy_page(request: Request) -> HTMLResponse:
    """매도 전략 분석 페이지"""
    return templates.TemplateResponse(
        "page/sell_strategy.html",
        {"request": request, "active_page": "sell_strategy"},
    )
