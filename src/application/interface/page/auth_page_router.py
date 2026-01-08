# -*- coding: utf-8 -*-
"""
Auth Page Router - 인증 관리 페이지
"""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(prefix="/page/auth", tags=["Page-Auth"], include_in_schema=False)


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def auth_page(request: Request) -> HTMLResponse:
    """인증 관리 페이지"""
    return templates.TemplateResponse(
        "page/auth.html", {"request": request, "active_page": "auth"}
    )
