from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from src.application.common.dependencies import AdminAccessDep

router = APIRouter(prefix="/ops", tags=["Operations Page"])
templates = Jinja2Templates(directory="templates")


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def operations_dashboard(
    request: Request,
    _: AdminAccessDep,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "page/ops.html",
        {
            "active_page": "ops",
            "page_title": "Operations Dashboard",
            "api_base": "/api/v1/ops",
        },
    )
