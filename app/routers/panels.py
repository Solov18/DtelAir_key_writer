from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.repositories.panel_repository import (
    create_or_update_panel,
    delete_panel,
    get_enabled_panels,
    update_panel,
)
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

    return RedirectResponse(
        url="/panels",
        status_code=303,
    )


@router.post("/panels/edit")
def panels_edit(
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

    return RedirectResponse(
        url="/panels",
        status_code=303,
    )


@router.post("/panels/delete")
def panels_delete(
    panel_id: int = Form(...),
):
    delete_panel(panel_id)

    return RedirectResponse(
        url="/panels",
        status_code=303,
    )