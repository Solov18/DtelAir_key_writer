from types import SimpleNamespace
from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.access_control import has_permission
from app.repositories.log_repository import get_last_operations
from app.repositories.role_repository import (
    ADMIN_CRITICAL_PERMISSIONS,
    create_role,
    delete_role,
    get_permissions,
    get_role,
    get_roles,
    get_users_for_role,
    set_role_permissions,
    update_role,
)
from app.repositories.system_settings_repository import (
    get_connection_check_results,
    get_monitor_runtime_settings,
    save_connection_check_result,
    save_monitor_runtime_settings,
)
from app.services.audit import log_event
from app.services.auth import get_current_user
from app.services.crm import check_crm_connection, crm_auth_configured
from app.services.panel_api import (
    check_panel_api_connection,
    panel_api_configured,
)
from app.services.system_diagnostics import (
    application_diagnostics,
    backup_diagnostics,
    connection_status,
    database_diagnostics,
    format_bytes,
    monitoring_diagnostics,
    overall_status,
    panel_registry_diagnostics,
    security_diagnostics,
    safe_public_url,
)
from app.settings import settings
from app.templates_config import templates


router = APIRouter()


def _can_manage(request: Request) -> bool:
    return has_permission(get_current_user(request), "manage_settings")


def _safe_return_path(value: str) -> str:
    value = (value or "/").strip()
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc or not value.startswith("/"):
        return "/"
    return value


def _settings_context(request: Request) -> dict:
    return {
        "request": request,
        "crm_ready": crm_auth_configured(),
        "dry_run": settings.dry_run,
        "panel_api_ready": panel_api_configured(),
        "session_secret_ready": (
            settings.session_secret != "change-this-secret-key-later"
            and len(settings.session_secret) >= 32
        ),
    }


def _actor_name(request: Request) -> str:
    user = request.session.get("user", {})
    return str(user.get("full_name") or user.get("login") or "Система")


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    if not _can_manage(request):
        return RedirectResponse("/?notice=admin_only", status_code=303)
    return templates.TemplateResponse("settings.html", _settings_context(request))


@router.get("/settings/mode", response_class=HTMLResponse)
def work_mode_page(request: Request):
    if not _can_manage(request):
        return RedirectResponse("/?notice=admin_only", status_code=303)
    return templates.TemplateResponse(
        "settings_mode.html",
        {
            **_settings_context(request),
            "training_enabled": bool(request.session.get("training_mode")),
        },
    )


@router.post("/settings/training-mode")
def training_mode_toggle(
    request: Request,
    enabled: int = Form(0),
    return_to: str = Form("/"),
):
    if not _can_manage(request):
        return RedirectResponse("/?notice=admin_only", status_code=303)
    request.session["training_mode"] = bool(enabled)
    log_event(
        request=request,
        action="settings_training_mode",
        object_type="Настройки",
        object_name="Режим работы",
        details="Учебный режим включён" if enabled else "Рабочий режим включён",
    )
    target = _safe_return_path(return_to)
    separator = "&" if "?" in target else "?"
    notice = "training_on" if enabled else "training_off"
    return RedirectResponse(
        f"{target}{separator}notice={notice}",
        status_code=303,
    )


@router.get("/settings/crm", response_class=HTMLResponse)
def crm_settings_page(request: Request):
    if not _can_manage(request):
        return RedirectResponse("/?notice=admin_only", status_code=303)
    context = _settings_context(request)
    try:
        check_results = get_connection_check_results()
    except Exception:
        check_results = {}
    check_results.update(request.session.get("connection_check_results", {}))
    database = database_diagnostics()
    application = application_diagnostics()
    backup = backup_diagnostics()
    security = security_diagnostics(request.url.scheme)
    try:
        monitor = monitoring_diagnostics()
    except Exception:
        monitor = {
            "status": "error",
            "status_label": "Ошибка",
            "message": "Состояние мониторинга недоступно",
            "checked_at": None,
            "enabled": False,
            "leader_active": False,
            "cycle_status": "unknown",
            "heartbeat": None,
            "heartbeat_stale": False,
            "last_cycle_at": None,
            "total": 0,
            "completed": 0,
            "online": 0,
            "failed": 0,
            "active_panels": 0,
            "next_cycle_at": None,
            "runtime": SimpleNamespace(
                panel_monitor_enabled=settings.panel_monitor_enabled,
                panel_monitor_interval_seconds=settings.panel_monitor_interval_seconds,
                panel_monitor_concurrency=settings.panel_monitor_concurrency,
                panel_monitor_stale_seconds=settings.panel_monitor_stale_seconds,
                panel_manual_check_cooldown_seconds=(
                    settings.panel_manual_check_cooldown_seconds
                ),
                updated_at=None,
                updated_by="",
            ),
        }
    try:
        panel_registry = panel_registry_diagnostics()
    except Exception:
        panel_registry = {
            "total": 0,
            "enabled": 0,
            "online": 0,
            "offline": 0,
            "stale": 0,
            "average_response_ms": None,
            "median_response_ms": None,
            "last_monitor_at": None,
            "last_success_at": None,
        }
    crm_health = connection_status(
        configured=crm_auth_configured(),
        last_result=check_results.get("crm"),
    )
    panel_health = connection_status(
        configured=panel_api_configured(),
        last_result=check_results.get("panels"),
    )
    health_items = [
        application,
        database,
        crm_health,
        panel_health,
        monitor,
        backup,
        security,
    ]
    context.update(
        {
            "database": database,
            "application": application,
            "backup": backup,
            "security": security,
            "panel_registry": panel_registry,
            "crm_health": crm_health,
            "panel_health": panel_health,
            "overall": overall_status(health_items),
            "health_items": health_items,
            "crm_base_url": safe_public_url(settings.crm_base_url),
            "crm_timeout": settings.request_timeout,
            "crm_buyer_id_ready": bool(settings.crm_buyer_id.strip()),
            "crm_login_ready": bool(settings.crm_login.strip()),
            "crm_password_ready": bool(settings.crm_password),
            "crm_cookie_ready": bool(settings.crm_cookie.strip()),
            "panel_api_login_ready": bool(settings.panel_api_login.strip()),
            "panel_api_password_ready": bool(settings.panel_api_password),
            "panel_api_timeout": settings.panel_api_timeout,
            "monitor": monitor,
            "monitor_settings": monitor["runtime"],
            "session_https_only": bool(settings.session_https_only),
            "check_results": check_results,
            "format_bytes": format_bytes,
            "runtime_notice": request.query_params.get("runtime_notice", ""),
            "runtime_error": request.query_params.get("runtime_error", ""),
        }
    )
    return templates.TemplateResponse("settings_crm.html", context)


@router.post("/settings/crm/check")
def crm_settings_check(request: Request):
    if not _can_manage(request):
        return RedirectResponse("/?notice=admin_only", status_code=303)
    result = check_crm_connection()
    request.session.setdefault("connection_check_results", {})["crm"] = result
    save_connection_check_result("crm", result, updated_by=_actor_name(request))
    log_event(
        request=request,
        action="settings_crm_check",
        object_type="Настройки",
        object_name="CRM DTEL",
        status="success" if result["ok"] else "error",
        details=(
            "Безопасная проверка CRM выполнена успешно"
            if result["ok"]
            else "Безопасная проверка CRM завершилась ошибкой"
        ),
    )
    return RedirectResponse("/settings/crm", status_code=303)


@router.post("/settings/panels/check")
def panel_api_settings_check(request: Request):
    if not _can_manage(request):
        return RedirectResponse("/?notice=admin_only", status_code=303)
    result = check_panel_api_connection()
    request.session.setdefault("connection_check_results", {})["panels"] = result
    save_connection_check_result("panels", result, updated_by=_actor_name(request))
    log_event(
        request=request,
        action="settings_panel_api_check",
        object_type="Настройки",
        object_name="API панелей",
        status="success" if result["ok"] else "error",
        details=(
            "Безопасная проверка API панелей выполнена успешно"
            if result["ok"]
            else "Безопасная проверка API панелей завершилась ошибкой"
        ),
    )
    return RedirectResponse("/settings/crm#panel-api", status_code=303)


@router.post("/settings/monitoring")
def monitoring_settings_update(
    request: Request,
    panel_monitor_enabled: int = Form(0),
    panel_monitor_interval_seconds: int = Form(...),
    panel_monitor_concurrency: int = Form(...),
    panel_monitor_stale_seconds: int = Form(...),
    panel_manual_check_cooldown_seconds: int = Form(...),
):
    if not _can_manage(request):
        return RedirectResponse("/?notice=admin_only", status_code=303)
    previous = get_monitor_runtime_settings()
    try:
        current = save_monitor_runtime_settings(
            {
                "panel_monitor_enabled": panel_monitor_enabled,
                "panel_monitor_interval_seconds": panel_monitor_interval_seconds,
                "panel_monitor_concurrency": panel_monitor_concurrency,
                "panel_monitor_stale_seconds": panel_monitor_stale_seconds,
                "panel_manual_check_cooldown_seconds": (
                    panel_manual_check_cooldown_seconds
                ),
            },
            updated_by=_actor_name(request),
        )
    except (TypeError, ValueError) as error:
        message = str(error)
        return RedirectResponse(
            f"/settings/crm?{urlencode({'runtime_error': message})}#monitoring",
            status_code=303,
        )
    changes = [
        key
        for key, value in current.values().items()
        if previous.values().get(key) != value
    ]
    log_event(
        request=request,
        action="settings_monitor_update",
        object_type="Настройки",
        object_name="Мониторинг панелей",
        details=(
            "Изменены параметры: " + ", ".join(changes)
            if changes
            else "Параметры сохранены без изменения значений"
        ),
    )
    return RedirectResponse(
        "/settings/crm?runtime_notice=saved#monitoring",
        status_code=303,
    )


@router.get("/settings/roles", response_class=HTMLResponse)
def roles_page(request: Request, selected_role_id: int = 0):
    if not _can_manage(request):
        return RedirectResponse("/?notice=admin_only", status_code=303)
    roles = get_roles()
    selected = get_role(selected_role_id) if selected_role_id else None
    if not selected and roles:
        selected = roles[0]
    return templates.TemplateResponse(
        "settings_roles.html",
        {
            "request": request,
            "roles": roles,
            "permissions": get_permissions(),
            "selected_role": selected,
            "role_users": get_users_for_role(selected["id"]) if selected else [],
            "critical_permissions": ADMIN_CRITICAL_PERMISSIONS,
        },
    )


@router.post("/settings/roles/create")
def roles_create(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    permissions: list[str] = Form([]),
):
    if not _can_manage(request):
        return RedirectResponse("/?notice=admin_only", status_code=303)
    try:
        role_id = create_role(name, description, set(permissions))
    except ValueError:
        return RedirectResponse(
            "/settings/roles?notice=role_create_error",
            status_code=303,
        )
    log_event(
        request=request,
        action="role_create",
        object_type="Роль",
        object_name=name.strip(),
        details="Создана пользовательская роль",
    )
    return RedirectResponse(
        f"/settings/roles?selected_role_id={role_id}&notice=role_created",
        status_code=303,
    )


@router.post("/settings/roles/{role_id}/update")
def roles_update(
    request: Request,
    role_id: int,
    name: str = Form(...),
    description: str = Form(""),
    permissions: list[str] = Form([]),
):
    if not _can_manage(request):
        return RedirectResponse("/?notice=admin_only", status_code=303)
    role = get_role(role_id)
    if not role:
        return RedirectResponse("/settings/roles?notice=role_missing", status_code=303)
    try:
        update_role(role_id, name, description)
        set_role_permissions(role_id, set(permissions))
    except ValueError:
        return RedirectResponse(
            f"/settings/roles?selected_role_id={role_id}&notice=role_update_error",
            status_code=303,
        )
    log_event(
        request=request,
        action="role_update",
        object_type="Роль",
        object_name=name.strip(),
        details="Название, описание и разрешения роли обновлены",
    )
    return RedirectResponse(
        f"/settings/roles?selected_role_id={role_id}&notice=role_updated",
        status_code=303,
    )


@router.post("/settings/roles/{role_id}/delete")
def roles_delete(request: Request, role_id: int):
    if not _can_manage(request):
        return RedirectResponse("/?notice=admin_only", status_code=303)
    role = get_role(role_id)
    if not role:
        return RedirectResponse("/settings/roles?notice=role_missing", status_code=303)
    try:
        delete_role(role_id)
    except ValueError:
        return RedirectResponse(
            f"/settings/roles?selected_role_id={role_id}&notice=role_delete_blocked",
            status_code=303,
        )
    log_event(
        request=request,
        action="role_delete",
        object_type="Роль",
        object_name=role["name"],
        details="Пользовательская роль удалена",
    )
    return RedirectResponse("/settings/roles?notice=role_deleted", status_code=303)


@router.get("/settings/security", response_class=HTMLResponse)
def security_log_page(request: Request):
    if not _can_manage(request):
        return RedirectResponse("/?notice=admin_only", status_code=303)
    security_prefixes = ("user_", "role_", "settings_")
    rows = [
        row
        for row in get_last_operations(500)
        if str(row.get("action") or "").startswith(security_prefixes)
    ]
    return templates.TemplateResponse(
        "settings_security.html",
        {"request": request, "rows": rows},
    )
