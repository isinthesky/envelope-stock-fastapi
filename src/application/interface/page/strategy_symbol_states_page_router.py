# -*- coding: utf-8 -*-
"""Strategy Symbol States Page Router - 전략 Symbol States 페이지"""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(
    prefix="/mypage/strategy/symbol-states",
    tags=["MyPage-Strategy"],
    include_in_schema=False,
)


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def strategy_symbol_states_page(request: Request) -> HTMLResponse:
    """전략 Symbol States 페이지"""
    return templates.TemplateResponse(
        "page/strategy_symbol_states.html",
        {
            "request": request,
            "active_page": "strategy",
        },
    )
