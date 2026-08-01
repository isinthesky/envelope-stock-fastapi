# -*- coding: utf-8 -*-
"""
Sell Strategy Page Router - 매도 전략 페이지 라우터
"""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from src.settings.config import settings

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(prefix="/mypage/sell-strategy", tags=["MyPage-SellStrategy"], include_in_schema=False)


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def sell_strategy_page(request: Request) -> HTMLResponse:
    """매도 전략 분석 페이지"""
    return templates.TemplateResponse(
        request,
        "page/sell_strategy.html",
        {
            "active_page": "sell_strategy",
            "static_version": settings.app_version,
            "etf_universe_enabled": settings.etf_universe_enabled,
            "etf_universe_count": len(settings.etf_universe_symbols),
        },
    )
