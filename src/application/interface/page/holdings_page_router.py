# -*- coding: utf-8 -*-
"""
Holdings Page Router - 보유 종목 매도 점검 페이지

사용자가 보유 종목코드/평단가/수량을 입력하고, 각 종목을 매도 시그널 분석
(sell-signal API)에 대입해 매도 단계(HOLD/REDUCE/EXIT)와 손익을 한눈에 본다.
입력값은 브라우저 localStorage에만 저장(서버 미저장).
"""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from src.settings.config import settings

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(prefix="/mypage/holdings", tags=["MyPage-Holdings"], include_in_schema=False)


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def holdings_page(request: Request) -> HTMLResponse:
    """보유 종목 매도 점검 페이지"""
    return templates.TemplateResponse(
        request,
        "page/holdings.html",
        {
            "active_page": "holdings",
            "static_version": settings.app_version,
            "etf_universe_enabled": settings.etf_universe_enabled,
            "etf_universe_count": len(settings.etf_universe_symbols),
        },
    )
