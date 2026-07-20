from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.repositories.panel_repository import (
    create_or_update_panel,
    delete_panel,
    get_enabled_panels,
    get_panel_by_id,
    update_panel,
)
from app.services.audit import log_event
from app.templates_config import templates


router = APIRouter()


@router.get("/panels", response_class=HTMLResponse)
def panels_page(request: Request):
    panels = get_enabled_panels()

    return templates.TemplateResponse(
        "panels.html",
        {
            "request": request,
            "panels": panels,
            "panels_count": len(panels),
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
    create_or_update_panel(
        address=address,
        entrance=entrance,
        mac=mac,
        ip=ip,
    )

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

    return RedirectResponse(
        url="/panels",
        status_code=303,
    )


@router.post("/panels/edit")
def panels_edit(
    request: Request,
    panel_id: int = Form(...),
    address: str = Form(...),
    mac: str = Form(...),
    entrance: str = Form(""),
    ip: str = Form(""),
):
    update_panel(
        panel_id=panel_id,
        address=address,
        entrance=entrance,
        mac=mac,
        ip=ip,
    )

    log_event(
        request=request,
        action="panel_update",
        object_type="Панель",
        object_name=f"{address} {entrance}".strip(),
        details=f"{address} / {entrance or 'вход не указан'} / {mac}",
        address=address,
        panel_name=f"{address} {entrance}".strip(),
        mac=mac,
    )

    return RedirectResponse(
        url="/panels",
        status_code=303,
    )


@router.post("/panels/delete")
def panels_delete(
    request: Request,
    panel_id: int = Form(...),
):
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
        )

    return RedirectResponse(
        url="/panels",
        status_code=303,
    )
