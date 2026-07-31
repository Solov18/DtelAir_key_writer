from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.repositories.dashboard_repository import get_dashboard_snapshot
from app.repositories.log_repository import get_recent_operations
from app.services.dashboard import (
    build_calendar,
    format_monitor_sync,
    monitor_status_view,
)
from app.templates_config import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    snapshot = get_dashboard_snapshot()
    monitor_status = monitor_status_view(snapshot)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "stats": snapshot,
            "recent_operations": get_recent_operations(5),
            "last_sync": format_monitor_sync(snapshot.get("monitor_finished_at")),
            "monitor_status": monitor_status,
            "calendar": build_calendar(),
        },
    )
