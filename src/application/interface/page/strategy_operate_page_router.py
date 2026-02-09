# -*- coding: utf-8 -*-
"""Strategy Operate Page Router - 전략 운영 페이지"""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from src.settings.config import settings

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(
    prefix="/mypage/strategy/operate",
    tags=["MyPage-Strategy"],
    include_in_schema=False,
)


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def strategy_operate_page(request: Request) -> HTMLResponse:
    """전략 운영 페이지"""
    return templates.TemplateResponse(
        "page/strategy_operate.html",
        {
            "request": request,
            "active_page": "strategy_operate",
            "static_version": settings.app_version,
        },
    )
