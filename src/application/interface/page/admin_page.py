# -*- coding: utf-8 -*-
"""
Admin Page Router - Jinja 기반 도메인 제어/조회 대시보드
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="templates")

router = APIRouter(prefix="/admin", tags=["AdminPage"])


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def admin_dashboard(request: Request) -> HTMLResponse:
    """도메인별 API 호출을 보조하는 관리자 대시보드"""
    return templates.TemplateResponse("admin_dashboard.html", {"request": request})

