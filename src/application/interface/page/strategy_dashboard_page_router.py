# -*- coding: utf-8 -*-
"""
Strategy Dashboard Page Router - 전략 대시보드 (통합 페이지)
"""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from src.settings.config import settings

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(prefix="/mypage/strategy", tags=["MyPage-Strategy"], include_in_schema=False)


@router.get("/dashboard", response_class=HTMLResponse)
async def strategy_dashboard_page(request: Request) -> HTMLResponse:
    """전략 대시보드 페이지"""
    return templates.TemplateResponse(
        request,
        "page/strategy_dashboard.html",
        {
            "active_page": "strategy_dashboard",
            "static_version": settings.app_version,
        },
    )
