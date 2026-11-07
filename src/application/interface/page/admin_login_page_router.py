# -*- coding: utf-8 -*-
"""
Admin Login Page Router - 관리자 로그인 페이지

IP allowlist(mypage include-level 게이트)만 통과하면 열리며, 로그인 자체는
`/api/v1/admin-auth/login`을 호출한다. 로그인 후 이동 경로(next)는 `/mypage/` 하위로만 제한한다.
"""
from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(prefix="/mypage/login", tags=["MyPage-Login"], include_in_schema=False)

DEFAULT_NEXT = "/mypage/order/"


def safe_next_path(next_path: str | None) -> str:
    """오픈 리다이렉트 방지: 같은 오리진의 /mypage/ 하위 또는 /ops 경로만 허용"""
    if (
        not next_path
        or not (next_path.startswith("/mypage/") or next_path in ("/ops", "/ops/"))
        or "//" in next_path
        or "\\" in next_path
        or next_path.startswith("/mypage/login")
    ):
        return DEFAULT_NEXT
    return next_path


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def login_page(
    request: Request,
    next_path: str | None = Query(default=None, alias="next"),
) -> HTMLResponse:
    """관리자 로그인 페이지"""
    return templates.TemplateResponse(
        request,
        "page/admin_login.html",
        {"next_path": safe_next_path(next_path)},
    )
