from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.templates_config import templates
from app.repositories.log_repository import get_last_operations

router = APIRouter()


@router.get("/log", response_class=HTMLResponse)
def log_page(request: Request):
    return templates.TemplateResponse(
        "log.html",
        {
            "request": request,
            "rows": get_last_operations(),
        },
    )