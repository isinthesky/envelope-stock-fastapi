# -*- coding: utf-8 -*-
"""
Strategy Dashboard Page Router - 전략 대시보드 (통합 페이지)
"""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from src.settings.config import settings

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(prefix="/mypage/strategy", tags=["MyPage-Strategy"], include_in_schema=False)


@router.get("/dashboard", response_class=HTMLResponse)
async def strategy_dashboard_page(request: Request) -> HTMLResponse:
    """전략 대시보드 페이지"""
    return templates.TemplateResponse(
        request,
        "page/strategy_dashboard.html",
        {
            "active_page": "strategy_dashboard",
            "static_version": settings.app_version,
            # 15:35 전략 자동 실행 경로 kill-switch 현재값 (표시 전용, 읽기만 한다).
            # OFF면 GoldenCrossEngine.execute가 주문 없이 에러만 담아 즉시 반환한다
            # (dry-run 대체 실행이 아니다). POST /api/v1/orders 수동 주문은 이 스위치와 무관하다.
            "strategy_live_trading_enabled": settings.strategy_live_trading_enabled,
        },
    )
