# -*- coding: utf-8 -*-
"""
Public Strategy Page Router - 공개용 Buy 전략 페이지 (nav bar 없음)

/page/ 경로로 접근 시 Buy 전략 페이지만 표시 (minimal layout)
"""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(prefix="/page", tags=["Page-Public"], include_in_schema=False)


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def public_strategy_page(request: Request) -> HTMLResponse:
    """공개용 Buy 전략 페이지 (nav bar 없음)"""
    return templates.TemplateResponse(
        request,
        "page/strategy_minimal.html", {"active_page": "strategy"}
    )
