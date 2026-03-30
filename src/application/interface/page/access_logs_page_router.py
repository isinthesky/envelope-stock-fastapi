# -*- coding: utf-8 -*-
"""
Access Logs Page Router - 접근 로그 페이지
"""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(prefix="/mypage/access-logs", tags=["MyPage-AccessLogs"], include_in_schema=False)


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def access_logs_page(request: Request) -> HTMLResponse:
    """접근 로그 페이지"""
    return templates.TemplateResponse(
        "page/access_logs.html", {"request": request, "active_page": "access_logs"}
    )
