from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.db import db
from app.settings import settings
from app.templates_config import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    with db() as conn:
        stats = {
            "keys": conn.execute("SELECT COUNT(*) FROM keys").fetchone()[0],
            "panels": conn.execute("SELECT COUNT(*) FROM panels WHERE enabled=1").fetchone()[0],
            "logs": conn.execute("SELECT COUNT(*) FROM operation_log").fetchone()[0],
        }

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "stats": stats,
            "dry_run": settings.dry_run,
        },
    )