# -*- coding: utf-8 -*-
"""
Backtest Page Router - 백테스팅 페이지
"""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(prefix="/mypage/backtest", tags=["MyPage-Backtest"], include_in_schema=False)


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def backtest_page(request: Request) -> HTMLResponse:
    """백테스팅 페이지"""
    return templates.TemplateResponse(
        "page/backtest.html", {"request": request, "active_page": "backtest"}
    )
