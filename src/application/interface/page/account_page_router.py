# -*- coding: utf-8 -*-
"""
Account Page Router - 계좌 관리 페이지
"""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(prefix="/mypage/account", tags=["MyPage-Account"], include_in_schema=False)


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def account_page(request: Request) -> HTMLResponse:
    """계좌 관리 페이지"""
    return templates.TemplateResponse(
        request,
        "page/account.html", {"active_page": "account"}
    )
