# -*- coding: utf-8 -*-
"""
WebSocket Page Router - WebSocket 상태 페이지
"""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(prefix="/mypage/websocket", tags=["MyPage-WebSocket"], include_in_schema=False)


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def websocket_page(request: Request) -> HTMLResponse:
    """WebSocket 상태 페이지"""
    return templates.TemplateResponse(
        request,
        "page/websocket.html", {"active_page": "websocket"}
    )
