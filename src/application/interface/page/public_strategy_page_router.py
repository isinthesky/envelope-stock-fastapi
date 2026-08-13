# -*- coding: utf-8 -*-
"""
Public Strategy Page Router - 공개 전략 포털 (/page/*)

관리자 의존성 없이 등록되는 공개 페이지:
- /page/                 : 전략 소개 (읽기 전용)
- /page/scan/            : 제한형 골든크로스 스캔 (공개 API 호출)
- /page/sell-analysis/   : 종목별 기술지표 매도 신호 분석
- /page/recommendations/ : 이전 URL 호환용 스캔 페이지 영구 리다이렉트

템플릿에는 active_page, 전략 설정값, static_version만 주입한다.
"""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from src.settings.config import settings

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(prefix="/page", tags=["Page-Public"], include_in_schema=False)


def _strategy_context() -> dict:
    """전략 설정값 (읽기 전용 표시용)"""
    return {
        "static_version": settings.app_version,
        "gc_short_ma": settings.gc_short_ma_period,
        "gc_long_ma": settings.gc_long_ma_period,
        # [regime] 진입 국면 게이트 현재값(상태 배지용, 읽기전용)
        "gc_regime_filter_enabled": settings.gc_regime_filter_enabled,
        "gc_regime_mode": settings.gc_regime_mode,
        "gc_regime_ma": settings.gc_regime_ma,
        "gc_regime_adx_min": settings.gc_regime_adx_min,
        "gc_regime_benchmark": settings.gc_regime_benchmark,
    }


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def public_strategy_overview_page(request: Request) -> HTMLResponse:
    """전략 소개 페이지"""
    return templates.TemplateResponse(
        request,
        "page/public_strategy_overview.html",
        {"active_page": "public_overview", **_strategy_context()},
    )


@router.get("/scan/", response_class=HTMLResponse)
async def public_strategy_scan_page(request: Request) -> HTMLResponse:
    """제한형 골든크로스 스캔 페이지"""
    return templates.TemplateResponse(
        request,
        "page/public_strategy_scan.html",
        {"active_page": "public_scan", **_strategy_context()},
    )


@router.get("/sell-analysis/", response_class=HTMLResponse)
async def public_sell_analysis_page(request: Request) -> HTMLResponse:
    """개인화 정보가 없는 공개 기술지표 매도 신호 분석 페이지."""
    return templates.TemplateResponse(
        request,
        "page/public_sell_analysis.html",
        {"active_page": "public_sell_analysis", **_strategy_context()},
    )


@router.get("/recommendations/", response_class=RedirectResponse)
async def public_strategy_recommendations_redirect() -> RedirectResponse:
    """폐기된 오늘의 추천 URL을 신호 등급별 스캔 결과 화면으로 영구 연결한다."""
    return RedirectResponse(url="/page/scan/", status_code=308)
