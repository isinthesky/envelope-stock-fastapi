# -*- coding: utf-8 -*-
"""
Public Strategy Page Router - 공개용 Buy 전략 페이지 (nav bar 없음)

/page/ 경로로 접근 시 Buy 전략 페이지만 표시 (minimal layout)
"""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from src.settings.config import settings

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(prefix="/page", tags=["Page-Public"], include_in_schema=False)


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def public_strategy_page(request: Request) -> HTMLResponse:
    """공개용 Buy 전략 페이지 (nav bar 없음)"""
    return templates.TemplateResponse(
        request,
        "page/strategy_minimal.html",
        {
            "active_page": "strategy",
            "gc_short_ma": settings.gc_short_ma_period,
            "gc_long_ma": settings.gc_long_ma_period,
            # [regime] 진입 국면 게이트 현재값(상태 배지용, 읽기전용)
            "gc_regime_filter_enabled": settings.gc_regime_filter_enabled,
            "gc_regime_mode": settings.gc_regime_mode,
            "gc_regime_ma": settings.gc_regime_ma,
            "gc_regime_adx_min": settings.gc_regime_adx_min,
            "gc_regime_benchmark": settings.gc_regime_benchmark,
        },
    )
