# -*- coding: utf-8 -*-
"""
Order Page Router - 주문 관리 페이지
"""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(prefix="/page/order", tags=["Page-Order"], include_in_schema=False)


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def order_page(request: Request) -> HTMLResponse:
    """주문 관리 페이지"""
    return templates.TemplateResponse(
        "page/order.html", {"request": request, "active_page": "order"}
    )
