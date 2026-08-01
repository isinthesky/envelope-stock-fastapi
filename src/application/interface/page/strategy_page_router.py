# -*- coding: utf-8 -*-
"""
Strategy Page Router - 전략 관리 페이지
"""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from src.settings.config import settings

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(prefix="/mypage/strategy", tags=["MyPage-Strategy"], include_in_schema=False)


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def strategy_page(request: Request) -> HTMLResponse:
    """전략 관리 페이지"""
    return templates.TemplateResponse(
        request,
        "page/strategy.html",
        {
            "active_page": "strategy",
            "static_version": settings.app_version,
            "gc_short_ma": settings.gc_short_ma_period,
            "gc_long_ma": settings.gc_long_ma_period,
            "etf_universe_enabled": settings.etf_universe_enabled,
            "etf_universe_count": len(settings.etf_universe_symbols),
        },
    )
