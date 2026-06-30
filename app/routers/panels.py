from io import BytesIO

from fastapi import APIRouter, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from openpyxl import Workbook

from app.services import import_panels_excel
from app.templates_config import templates
from app.repositories.panel_repository import (
    get_enabled_panels,
    create_or_update_panel,
    update_panel,
    soft_delete_panel,
)

router = APIRouter()


@router.get("/panels", response_class=HTMLResponse)
def panels_page(request: Request):
    return templates.TemplateResponse(
        "panels.html",
        {
            "request": request,
            "panels": get_enabled_panels(),
        },
    )


@router.post("/panels/add")
def panels_add(
    address: str = Form(...),
    name: str = Form(...),
    mac: str = Form(...),
    entrance: str = Form(""),
    tags: str = Form(""),
):
    create_or_update_panel(
        address=address,
        entrance=entrance,
        name=name,
        mac=mac,
        tags=tags,
    )

    return RedirectResponse("/panels", status_code=303)


@router.post("/panels/edit")
def panels_edit(
    panel_id: int = Form(...),
    address: str = Form(...),
    entrance: str = Form(""),
    name: str = Form(...),
    mac: str = Form(...),
    tags: str = Form(""),
):
    update_panel(
        panel_id=panel_id,
        address=address,
        entrance=entrance,
        name=name,
        mac=mac,
        tags=tags,
    )

    return RedirectResponse("/panels", status_code=303)


@router.post("/panels/delete")
def panels_delete(panel_id: int = Form(...)):
    soft_delete_panel(panel_id)

    return RedirectResponse("/panels", status_code=303)


@router.get("/panels/export")
def panels_export():
    rows = get_enabled_panels()

    wb = Workbook()
    ws = wb.active
    ws.title = "Панели"

    ws.append([
        "ID",
        "Адрес",
        "Вход",
        "Панель",
        "MAC",
        "Теги",
    ])

    for r in rows:
        ws.append([
            r["id"],
            r["address"],
            r["entrance"],
            r["name"],
            r["mac"],
            r["tags"],
        ])

    stream = BytesIO()
    wb.save(stream)
    stream.seek(0)

    return Response(
        content=stream.read(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": 'attachment; filename="panels.xlsx"',
        },
    )


@router.post("/panels/import")
async def panels_import(file: UploadFile = File(...)):
    result = import_panels_excel(
        file.filename,
        await file.read(),
    )

    return RedirectResponse(
        f"/panels?added={result['added']}&updated={result['updated']}&skipped={result['skipped']}&errors={result['errors']}",
        status_code=303,
    )