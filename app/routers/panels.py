import io
from urllib.parse import urlencode

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from openpyxl import Workbook

from app.access_control import has_permission
from app.repositories.panel_repository import (
    create_or_update_panel,
    delete_panel,
    get_all_panels,
    get_panel_by_id,
    get_panel_filter_options,
    get_panel_page,
    get_panel_statistics,
    normalize_panel_row,
    seconds_since_last_check,
    set_panel_enabled,
    update_panel,
    update_panel_api_status,
)
from app.repositories.panel_monitor_repository import (
    get_monitor_state,
    request_monitor_cycle,
)
from app.repositories.system_settings_repository import (
    get_monitor_runtime_settings,
)
from app.services import import_panels_excel
from app.services.audit import log_event
from app.services.auth import get_current_user
from app.services.excel_export import excel_safe_value
from app.services.panel_api import (
    PanelApiError,
    check_panel,
    get_panel_snapshot,
    panel_api_configured,
    reboot_panel,
)
from app.templates_config import templates


router = APIRouter()


def _user_name(request: Request) -> str:
    user = request.session.get("user", {})
    return user.get("full_name") or user.get("login") or "Система"


def _is_admin(request: Request) -> bool:
    return has_permission(get_current_user(request), "manage_panels")


def _panels_redirect(**params) -> RedirectResponse:
    clean = {key: value for key, value in params.items() if value not in (None, "")}
    query = f"?{urlencode(clean)}" if clean else ""
    return RedirectResponse(f"/panels{query}", status_code=303)


@router.get("/panels", response_class=HTMLResponse)
def panels_page(
    request: Request,
    q: str = "",
    status: str = "",
    address: str = "",
    entrance: str = "",
    page: int = 1,
    selected_panel_id: int = 0,
):
    runtime = get_monitor_runtime_settings()
    monitor_state = get_monitor_state()
    checking_panel_ids = {
        int(value) for value in monitor_state.get("active_panel_ids", [])
    }
    panel_page = get_panel_page(
        query=q,
        status=status,
        address=address,
        entrance=entrance,
        page=page,
        page_size=20,
        stale_after_seconds=runtime.panel_monitor_stale_seconds,
        checking_panel_ids=checking_panel_ids,
    )
    selected_panel = get_panel_by_id(selected_panel_id) if selected_panel_id else None
    if not selected_panel and panel_page["items"]:
        selected_panel = panel_page["items"][0]
    elif selected_panel:
        selected_panel = normalize_panel_row(
            selected_panel,
            checking_panel_ids=checking_panel_ids,
            stale_after_seconds=runtime.panel_monitor_stale_seconds,
        )

    filters = {
        "q": q,
        "status": status,
        "address": address,
        "entrance": entrance,
    }
    base_params = {
        name: value
        for name, value in filters.items()
        if value not in (None, "")
    }
    base_query = urlencode(base_params)
    row_query = urlencode({**base_params, "page": panel_page["page"]})

    import_report = None
    if request.query_params.get("imported") == "1":
        import_report = {
            key: int(request.query_params.get(key, "0") or 0)
            for key in ("added", "updated", "skipped", "errors")
        }

    return templates.TemplateResponse(
        "panels.html",
        {
            "request": request,
            "panels": panel_page["items"],
            "panel_page": panel_page,
            "statistics": get_panel_statistics(
                runtime.panel_monitor_stale_seconds
            ),
            "monitor_state": monitor_state,
            "filter_options": get_panel_filter_options(),
            "filters": filters,
            "base_query": base_query,
            "row_query": row_query,
            "selected_panel": selected_panel,
            "api_configured": panel_api_configured(),
            "is_admin": _is_admin(request),
            "import_report": import_report,
            "message": request.query_params.get("message", ""),
            "error": request.query_params.get("error", ""),
        },
    )


@router.post("/panels/add")
def panels_add(
    request: Request,
    address: str = Form(...),
    mac: str = Form(...),
    entrance: str = Form(""),
    ip: str = Form(""),
):
    try:
        create_or_update_panel(address=address, entrance=entrance, mac=mac, ip=ip)
    except ValueError as error:
        return _panels_redirect(error=str(error))

    log_event(
        request=request,
        action="panel_create",
        object_type="Панель",
        object_name=f"{address} {entrance}".strip(),
        details=f"{address} / {entrance or 'вход не указан'} / {mac}",
        address=address,
        panel_name=f"{address} {entrance}".strip(),
        mac=mac,
    )
    return _panels_redirect(message="Панель сохранена")


@router.post("/panels/edit")
def panels_edit(
    request: Request,
    panel_id: int = Form(...),
    address: str = Form(...),
    mac: str = Form(...),
    entrance: str = Form(""),
    ip: str = Form(""),
):
    try:
        update_panel(panel_id=panel_id, address=address, entrance=entrance, mac=mac, ip=ip)
    except ValueError as error:
        return _panels_redirect(error=str(error), selected_panel_id=panel_id)

    log_event(
        request=request,
        action="panel_update",
        object_type="Панель",
        object_name=f"{address} {entrance}".strip(),
        details=f"{address} / {entrance or 'вход не указан'} / {mac}",
        address=address,
        panel_name=f"{address} {entrance}".strip(),
        mac=mac,
        panel_id=panel_id,
    )
    return _panels_redirect(message="Данные панели обновлены", selected_panel_id=panel_id)


@router.post("/panels/monitor/start")
def panels_monitor_start(request: Request):
    if not _is_admin(request):
        return JSONResponse(
            {"ok": False, "error": "Недостаточно прав для запуска мониторинга"},
            status_code=403,
        )
    if not panel_api_configured():
        return JSONResponse(
            {"ok": False, "error": "Сначала настройте общие реквизиты API панелей"},
            status_code=409,
        )
    state, created = request_monitor_cycle(_user_name(request))
    log_event(
        request=request,
        action="panel_monitor_request",
        object_type="Панели",
        object_name="Общий мониторинг",
        details=(
            "Поставлен в очередь общий цикл мониторинга"
            if created
            else "Используется уже запущенный общий цикл мониторинга"
        ),
        status="success",
    )
    return JSONResponse(
        jsonable_encoder({
            "ok": True,
            "created": created,
            "monitor": state,
            "message": (
                "Обновление мониторинга поставлено в очередь"
                if created
                else "Мониторинг уже выполняется"
            ),
        }),
        status_code=202,
    )


@router.get("/panels/monitor/state")
def panels_monitor_state(
    q: str = "",
    status: str = "",
    address: str = "",
    entrance: str = "",
    page: int = 1,
):
    runtime = get_monitor_runtime_settings()
    state = get_monitor_state()
    checking_panel_ids = {
        int(value) for value in state.get("active_panel_ids", [])
    }
    panel_page = get_panel_page(
        query=q,
        status=status,
        address=address,
        entrance=entrance,
        page=page,
        page_size=20,
        stale_after_seconds=runtime.panel_monitor_stale_seconds,
        checking_panel_ids=checking_panel_ids,
    )
    return JSONResponse(
        jsonable_encoder(
            {
                "ok": True,
                "monitor": state,
                "statistics": get_panel_statistics(
                    runtime.panel_monitor_stale_seconds
                ),
                "items": panel_page["items"],
            }
        )
    )


@router.post("/panels/{panel_id}/check")
async def panel_check(request: Request, panel_id: int):
    if not _is_admin(request):
        return JSONResponse(
            {"ok": False, "error": "Недостаточно прав для проверки панели"},
            status_code=403,
        )
    panel = get_panel_by_id(panel_id)
    if not panel:
        return JSONResponse({"ok": False, "error": "Панель не найдена"}, status_code=404)
    if not panel.get("enabled"):
        return JSONResponse({"ok": False, "error": "Панель отключена в учёте"}, status_code=409)
    monitor_state = get_monitor_state()
    if monitor_state.get("status") in {"queued", "running"}:
        return JSONResponse(
            {
                "ok": False,
                "error": (
                    "Сейчас выполняется общий мониторинг. "
                    "Дождитесь его завершения, чтобы не отправлять панели повторный запрос."
                ),
            },
            status_code=409,
        )
    since_last_check = seconds_since_last_check(panel_id)
    runtime = get_monitor_runtime_settings()
    cooldown = runtime.panel_manual_check_cooldown_seconds
    if since_last_check is not None and since_last_check < cooldown:
        retry_after = max(1, round(cooldown - since_last_check))
        return JSONResponse(
            {
                "ok": False,
                "error": f"Повторная проверка будет доступна через {retry_after} сек.",
                "retry_after": retry_after,
            },
            status_code=429,
        )
    result = await run_in_threadpool(check_panel, panel)
    update_panel_api_status(panel_id, result)
    updated_panel = get_panel_by_id(panel_id)
    log_event(
        request=request,
        action="panel_check",
        object_type="Панель",
        object_name=panel.get("name") or str(panel_id),
        details=f"Ручная проверка панели ID {panel_id}",
        status="success" if result.get("status") == "online" else "warning",
        panel_id=panel_id,
        address=panel.get("address", ""),
        panel_name=panel.get("name", ""),
        mac=panel.get("mac", ""),
    )
    return JSONResponse(
        jsonable_encoder(
            {
                "ok": True,
                "panel": updated_panel,
                "statistics": get_panel_statistics(
                    runtime.panel_monitor_stale_seconds
                ),
            }
        )
    )


@router.get("/panels/{panel_id}/snapshot")
def panel_snapshot(panel_id: int):
    panel = get_panel_by_id(panel_id)
    if not panel:
        return JSONResponse({"ok": False, "error": "Панель не найдена"}, status_code=404)
    try:
        content, content_type = get_panel_snapshot(panel)
    except PanelApiError as error:
        return JSONResponse({"ok": False, "error": str(error)}, status_code=502)
    return Response(
        content=content,
        media_type=content_type,
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@router.post("/panels/{panel_id}/reboot")
def panel_reboot(request: Request, panel_id: int):
    if not _is_admin(request):
        return JSONResponse({"ok": False, "error": "Перезагрузка доступна только администратору"}, status_code=403)
    panel = get_panel_by_id(panel_id)
    if not panel:
        return JSONResponse({"ok": False, "error": "Панель не найдена"}, status_code=404)
    try:
        reboot_panel(panel)
    except PanelApiError as error:
        return JSONResponse({"ok": False, "error": str(error)}, status_code=502)

    log_event(
        request=request,
        action="panel_reboot",
        object_type="Панель",
        object_name=panel.get("name") or str(panel_id),
        details=f"Отправлена команда перезагрузки на {panel.get('ip')}",
        address=panel.get("address", ""),
        panel_name=panel.get("name", ""),
        mac=panel.get("mac", ""),
        panel_id=panel_id,
    )
    return JSONResponse({"ok": True, "message": "Команда перезагрузки отправлена"})


@router.post("/panels/{panel_id}/toggle")
def panel_toggle(request: Request, panel_id: int, enabled: int = Form(...)):
    if not _is_admin(request):
        return _panels_redirect(error="Изменение состояния доступно только администратору")
    panel = get_panel_by_id(panel_id)
    try:
        set_panel_enabled(panel_id, bool(enabled))
    except ValueError as error:
        return _panels_redirect(error=str(error))
    log_event(
        request=request,
        action="panel_enable" if enabled else "panel_disable",
        object_type="Панель",
        object_name=(panel or {}).get("name") or str(panel_id),
        details="Панель возвращена в работу" if enabled else "Панель отключена только в локальном учёте",
        address=(panel or {}).get("address", ""),
        panel_name=(panel or {}).get("name", ""),
        mac=(panel or {}).get("mac", ""),
        panel_id=panel_id,
    )
    return _panels_redirect(message="Состояние панели изменено", selected_panel_id=panel_id)


@router.post("/panels/import")
async def panels_import(request: Request, file: UploadFile = File(...)):
    report = import_panels_excel(file.filename or "", await file.read())
    log_event(
        request=request,
        action="panel_import",
        object_type="Файл панелей",
        object_name=file.filename or "Импорт",
        details=(
            f"Добавлено: {report['added']}; обновлено: {report['updated']}; "
            f"пропущено: {report['skipped']}; ошибок: {report['errors']}"
        ),
        status="success" if report["errors"] == 0 else "warning",
    )
    return _panels_redirect(imported=1, **report)


@router.get("/panels/export")
def panels_export():
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Панели"
    sheet.append(
        [
            "ID", "Адрес", "Подъезд / вход", "Название", "IP", "MAC",
            "Состояние", "Напряжение питания", "Модель", "Прошивка",
            "Последняя проверка", "Последний онлайн",
        ]
    )
    for panel in get_all_panels():
        sheet.append(
            [
                panel["id"], panel["address"], panel["entrance"], panel["name"],
                panel["ip"], panel["mac"], panel["status_name"], panel.get("supply_voltage", ""),
                panel.get("device_model", ""), panel.get("firmware_version", ""),
                excel_safe_value(panel.get("last_checked_at", "")),
                excel_safe_value(panel.get("last_online_at", "")),
            ]
        )
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    output = io.BytesIO()
    workbook.save(output)
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="panels_export.xlsx"'},
    )


@router.post("/panels/delete")
def panels_delete(request: Request, panel_id: int = Form(...)):
    if not _is_admin(request):
        return _panels_redirect(error="Удаление доступно только администратору")
    panel = get_panel_by_id(panel_id)
    delete_panel(panel_id)
    if panel:
        log_event(
            request=request,
            action="panel_delete",
            object_type="Панель",
            object_name=panel.get("name") or panel.get("address") or str(panel_id),
            details=f"{panel.get('address', '')} / {panel.get('entrance') or 'вход не указан'} / {panel.get('mac', '')}",
            address=panel.get("address", ""),
            panel_name=panel.get("name", ""),
            mac=panel.get("mac", ""),
            panel_id=panel_id,
        )
    return _panels_redirect(message="Панель удалена")
