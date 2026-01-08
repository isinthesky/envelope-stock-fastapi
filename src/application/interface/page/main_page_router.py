# -*- coding: utf-8 -*-
"""
Main Page Router - 메인 대시보드 (도메인 페이지 허브)
"""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

# 프로젝트 루트 기준 절대 경로로 templates 설정
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(prefix="/page", tags=["Page"], include_in_schema=False)


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def main_dashboard(request: Request) -> HTMLResponse:
    """메인 대시보드 - 도메인별 페이지 허브"""
    return templates.TemplateResponse(
        "page/index.html", {"request": request, "active_page": "index"}
    )
