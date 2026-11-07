# -*- coding: utf-8 -*-
"""
Order Page Router - 주문 관리 페이지

실계좌 주문 화면이므로 IP allowlist에 더해 관리자 로그인 세션을 요구한다.
미로그인 시 로그인 페이지로 303 리다이렉트한다.
"""
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from src.application.common.dependencies import OptionalAdminSessionDep

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(prefix="/mypage/order", tags=["MyPage-Order"], include_in_schema=False)


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def order_page(request: Request, admin_session: OptionalAdminSessionDep) -> Response:
    """주문 관리 페이지"""
    if admin_session is None:
        return RedirectResponse(
            url=f"/mypage/login/?next={quote('/mypage/order/', safe='')}",
            status_code=303,
        )
    return templates.TemplateResponse(
        request,
        "page/order.html",
        {"active_page": "order", "admin_username": admin_session.username},
    )
