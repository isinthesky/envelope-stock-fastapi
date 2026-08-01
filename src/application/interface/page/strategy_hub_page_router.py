# -*- coding: utf-8 -*-
"""
Strategy Hub Page Router - 전략 센터(통합)

기존 매수 스캔 / 추천·룰셋 / 내 전략 페이지를 하나의 탭 화면으로 통합.
각 탭은 기존 페이지를 embed 모드 iframe으로 로드해 기능은 그대로 보존한다.
"""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from src.settings.config import settings

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(prefix="/mypage/strategy-hub", tags=["MyPage-StrategyHub"], include_in_schema=False)


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def strategy_hub_page(request: Request) -> HTMLResponse:
    """전략 센터(통합 탭) 페이지"""
    return templates.TemplateResponse(
        request,
        "page/strategy_hub.html",
        {
            "active_page": "strategy_hub",
            "static_version": settings.app_version,
        },
    )
