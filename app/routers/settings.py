from urllib.parse import urlparse

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.access_control import ROLE_DEFINITIONS, ROLE_ORDER
from app.services.auth import get_current_user, is_admin
from app.services.crm import crm_auth_configured
from app.settings import settings
from app.templates_config import templates

router = APIRouter()


def _safe_return_path(value: str) -> str:
    value = (value or "/").strip()
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc or not value.startswith("/"):
        return "/"
    return value


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    user = get_current_user(request)
    if not is_admin(user):
        return RedirectResponse("/?notice=admin_only", status_code=303)

    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "roles": [
                {
                    "code": code,
                    **ROLE_DEFINITIONS[code],
                }
                for code in ROLE_ORDER
            ],
            "crm_ready": crm_auth_configured(),
            "dry_run": settings.dry_run,
            "panel_api_ready": bool(
                settings.panel_api_login and settings.panel_api_password
            ),
            "session_secret_ready": (
                settings.session_secret != "change-this-secret-key-later"
                and len(settings.session_secret) >= 32
            ),
        },
    )


@router.post("/settings/training-mode")
def training_mode_toggle(
    request: Request,
    enabled: int = Form(0),
    return_to: str = Form("/"),
):
    request.session["training_mode"] = bool(enabled)
    target = _safe_return_path(return_to)
    separator = "&" if "?" in target else "?"
    notice = "training_on" if enabled else "training_off"
    return RedirectResponse(
        f"{target}{separator}notice={notice}",
        status_code=303,
    )
