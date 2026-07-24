from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.db import db
from app.settings import settings
from app.templates_config import templates
from app.repositories.log_repository import get_recent_operations
from app.services.crm import crm_auth_configured
from app.repositories.panel_repository import get_panel_statistics

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    with db() as conn:
        stats = {
            "keys": conn.execute(
                "SELECT COUNT(*) FROM keys WHERE TRIM(hex_value) <> ''"
            ).fetchone()[0],
            "panels": conn.execute(
                "SELECT COUNT(*) FROM panels WHERE enabled = 1"
            ).fetchone()[0],
            "logs": conn.execute(
                "SELECT COUNT(*) FROM operation_log"
            ).fetchone()[0],
            "employees": conn.execute(
                "SELECT COUNT(*) FROM employees WHERE enabled = 1"
            ).fetchone()[0],
            "uk": conn.execute(
                "SELECT COUNT(*) FROM uk_groups"
            ).fetchone()[0],
        }

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "stats": stats,
            "recent_operations": get_recent_operations(5),
            "dry_run": settings.dry_run,
            "crm_ready": crm_auth_configured(),
            "panel_stats": get_panel_statistics(),
            "training": bool(request.session.get("training_mode")),
        },
    )
