# -*- coding: utf-8 -*-
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from src.settings.config import settings

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(
    prefix="/mypage/recommendation",
    tags=["MyPage-Recommendation"],
    include_in_schema=False,
)


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def recommendation_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "page/recommendation.html",
        {
            "request": request,
            "active_page": "recommendation",
            "static_version": settings.app_version,
        },
    )
