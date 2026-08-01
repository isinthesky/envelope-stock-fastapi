# -*- coding: utf-8 -*-
"""
Research Page Router - 전략 연구 & 백테스트 이력 페이지

이번 개선 사이클(계산식 blind-spot 수정, OHLCV 저장 수정, ETF 백테스트,
추세추종·레짐필터 검증, dead code 정리)의 결과를 정리해 보여준다.
"""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from src.settings.config import settings

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(prefix="/mypage/research", tags=["MyPage-Research"], include_in_schema=False)


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def research_page(request: Request) -> HTMLResponse:
    """전략 연구 & 백테스트 이력 페이지"""
    return templates.TemplateResponse(
        request,
        "page/research.html",
        {
            "active_page": "research",
            "static_version": settings.app_version,
            # 운영 반영된 전략 플래그 현재값(활성화 여부 표시)
            "flags": {
                "etf_universe_enabled": settings.etf_universe_enabled,
                "etf_universe_count": len(settings.etf_universe_symbols),
                "gc_short_ma_period": settings.gc_short_ma_period,
                "gc_long_ma_period": settings.gc_long_ma_period,
                "gc_regime_filter_enabled": settings.gc_regime_filter_enabled,
                "gc_regime_ma": settings.gc_regime_ma,
                "gc_require_rsi_oversold": settings.gc_require_rsi_oversold,
                "gc_rsi_threshold": settings.gc_rsi_threshold,
                "fear_buy_window_enabled": settings.fear_buy_window_enabled,
                "fear_buy_notify_enabled": settings.fear_buy_notify_enabled,
                "ohlcv_retention_days": settings.ohlcv_retention_days,
            },
        },
    )
