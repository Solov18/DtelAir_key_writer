import io
import re
from urllib.parse import urlencode

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from openpyxl import Workbook

from app.repositories.key_repository import (
    KEY_STATUSES,
    create_key_type,
    get_all_keys_for_export,
    get_key,
    get_key_assignments,
    get_key_history,
    get_key_statistics,
    get_key_type,
    get_key_types,
    get_keys_page,
    get_missing_key_numbers,
    key_status_name,
    prepare_key_range,
    release_key,
    save_key_hex,
    save_prepared_key,
    set_key_status,
    update_key,
    update_key_type,
)
from app.repositories.log_repository import normalize_operation_row
from app.services import import_keys_file
from app.services.audit import log_event
from app.templates_config import templates

router = APIRouter()


def _user_name(request: Request) -> str:
    user = request.session.get("user", {})
    return user.get("full_name") or user.get("login") or "Система"


def _keys_redirect(**params) -> RedirectResponse:
    clean_params = {
        key: value
        for key, value in params.items()
        if value not in (None, "")
    }
    suffix = f"?{urlencode(clean_params)}" if clean_params else ""
    return RedirectResponse(f"/keys{suffix}", status_code=303)


def _import_report_from_query(request: Request) -> dict | None:
    if request.query_params.get("imported") != "1":
        return None

    names = ("created_types", "added", "updated", "duplicates", "errors")
    return {
        name: int(request.query_params.get(name, "0") or 0)
        for name in names
    }


@router.get("/keys", response_class=HTMLResponse)
def keys_page(
    request: Request,
    q: str = "",
    key_type_id: int = 0,
    status: str = "",
    availability: str = "",
    added_from: str = "",
    added_to: str = "",
    assigned_from: str = "",
    assigned_to: str = "",
    page: int = 1,
    selected_key_id: int = 0,
):
    key_page = get_keys_page(
        query=q,
        key_type_id=key_type_id or None,
        status=status,
        availability=availability,
        added_from=added_from,
        added_to=added_to,
        assigned_from=assigned_from,
        assigned_to=assigned_to,
        page=page,
        page_size=20,
    )

    selected_key = get_key(selected_key_id) if selected_key_id else None
    if not selected_key and key_page["items"]:
        selected_key = get_key(key_page["items"][0]["id"])

    selected_history = []
    if selected_key:
        selected_history = [
            normalize_operation_row(item)
            for item in get_key_history(selected_key["id"], limit=4)
        ]

    filters = {
        "q": q,
        "key_type_id": key_type_id,
        "status": status,
        "availability": availability,
        "added_from": added_from,
        "added_to": added_to,
        "assigned_from": assigned_from,
        "assigned_to": assigned_to,
    }
    base_query = urlencode(
        {
            name: value
            for name, value in filters.items()
            if value not in (None, "", 0)
        }
    )
    row_query = urlencode(
        {
            **{
                name: value
                for name, value in filters.items()
                if value not in (None, "", 0)
            },
            "page": key_page["page"],
        }
    )

    return templates.TemplateResponse(
        "keys.html",
        {
            "request": request,
            "keys": key_page["items"],
            "key_page": key_page,
            "key_types": get_key_types(),
            "active_key_types": get_key_types(include_archived=False),
            "key_statuses": KEY_STATUSES,
            "statistics": get_key_statistics(),
            "filters": filters,
            "selected_key": selected_key,
            "selected_history": selected_history,
            "base_query": base_query,
            "row_query": row_query,
            "row_offset": (key_page["page"] - 1) * key_page["page_size"],
            "import_report": _import_report_from_query(request),
            "message": request.query_params.get("message", ""),
            "error": request.query_params.get("error", ""),
        },
    )


@router.post("/keys/types")
def key_type_create(
    request: Request,
    name: str = Form(...),
    color: str = Form("#2A9DF4"),
    note: str = Form(""),
):
    try:
        key_type_id = create_key_type(name, color, note)
    except ValueError as error:
        return _keys_redirect(error=str(error))

    log_event(
        request=request,
        action="key_type_create",
        object_type="Тип ключа",
        object_name=name.strip(),
        details="Создан новый тип ключа",
    )
    return _keys_redirect(message="Тип ключа создан", edit_type=key_type_id)


@router.post("/keys/types/{key_type_id}")
def key_type_update(
    request: Request,
    key_type_id: int,
    name: str = Form(...),
    color: str = Form("#2A9DF4"),
    note: str = Form(""),
    enabled: str = Form("0"),
):
    try:
        update_key_type(
            key_type_id,
            name,
            color,
            note,
            enabled == "1",
        )
    except ValueError as error:
        return _keys_redirect(error=str(error))

    log_event(
        request=request,
        action="key_type_update",
        object_type="Тип ключа",
        object_name=name.strip(),
        details="Обновлены параметры типа ключа",
    )
    return _keys_redirect(message="Тип ключа обновлён")


@router.post("/keys/prepare", response_class=HTMLResponse)
def keys_prepare(
    request: Request,
    key_type_id: int = Form(...),
    start_number: str = Form(...),
    count: int = Form(...),
):
    try:
        batch = prepare_key_range(
            key_type_id,
            start_number,
            count,
            _user_name(request),
        )
    except ValueError as error:
        return _keys_redirect(error=str(error))

    log_event(
        request=request,
        action="keys_prepare",
        object_type="Партия ключей",
        object_name=f"{batch['key_type']['name']} №{batch['start']}–{batch['end']}",
        details=(
            f"Подготовлено к считыванию: {len(batch['rows'])}; "
            f"уже были готовы: {batch['filled_existing']}. "
            "Записи без HEX не создавались."
        ),
    )

    return templates.TemplateResponse(
        "keys_prepare.html",
        {
            "request": request,
            "batch": batch,
        },
    )


@router.get("/keys/arbitrary", response_class=HTMLResponse)
def keys_arbitrary(
    request: Request,
    key_type_id: int = Query(...),
    count: int = Query(1),
    suggested_number: str = Query(""),
):
    key_type = get_key_type(key_type_id)
    if not key_type or not key_type.get("enabled"):
        return _keys_redirect(error="Выберите активный тип ключа.")
    if count < 1 or count > 500:
        return _keys_redirect(error="За один раз можно добавить от 1 до 500 произвольных ключей.")

    clean_suggestion = suggested_number.strip()
    if clean_suggestion and not re.fullmatch(r"[0-9]+", clean_suggestion):
        return _keys_redirect(error="Предложенный номер должен состоять только из цифр.")

    return templates.TemplateResponse(
        "keys_arbitrary.html",
        {
            "request": request,
            "key_type": key_type,
            "rows": [
                {
                    "index": index + 1,
                    "number": clean_suggestion if index == 0 else "",
                }
                for index in range(count)
            ],
        },
    )


@router.get("/keys/missing", response_class=HTMLResponse)
def keys_missing(
    request: Request,
    key_type_id: int = Query(...),
    start_number: str = Query(""),
    end_number: str = Query(""),
):
    try:
        result = get_missing_key_numbers(
            key_type_id,
            start_number,
            end_number,
        )
    except ValueError as error:
        return _keys_redirect(error=str(error))

    return templates.TemplateResponse(
        "keys_missing.html",
        {
            "request": request,
            "result": result,
            "active_key_types": get_key_types(include_archived=False),
        },
    )


@router.post("/keys/scan")
async def prepared_key_hex_save(request: Request):
    try:
        payload = await request.json()
        allow_replace = bool(payload.get("replace", False))
        key = save_prepared_key(
            int(payload.get("key_type_id", 0)),
            str(payload.get("number", "")),
            str(payload.get("hex_value", "")),
            _user_name(request),
            allow_replace=allow_replace,
        )
    except (ValueError, TypeError) as error:
        return JSONResponse(
            {"ok": False, "error": str(error)},
            status_code=400,
        )

    log_event(
        request=request,
        action="key_hex_scan",
        object_type="Ключ",
        object_name=f"{key['type_name']} №{key['number']}",
        details=(
            "HEX исправлен и сохранён"
            if allow_replace
            else "Ключ создан вместе с HEX"
        ),
        key_id=key["id"],
        key_type=key["type_name"],
        printed_number=key["number"],
        hex_value=key["hex_value"],
    )
    return JSONResponse(
        {
            "ok": True,
            "key_id": key["id"],
            "hex_value": key["hex_value"],
            "message": (
                "Исправление сохранено"
                if allow_replace
                else "Ключ и HEX сохранены автоматически"
            ),
        }
    )


@router.post("/keys/{key_id}/hex")
async def key_hex_save(request: Request, key_id: int):
    try:
        payload = await request.json()
        allow_replace = bool(payload.get("replace", False))
        key = save_key_hex(
            key_id,
            str(payload.get("hex_value", "")),
            _user_name(request),
            allow_replace=allow_replace,
        )
    except (ValueError, TypeError) as error:
        return JSONResponse(
            {"ok": False, "error": str(error)},
            status_code=400,
        )

    log_event(
        request=request,
        action="key_hex_scan",
        object_type="Ключ",
        object_name=f"{key['type_name']} №{key['number']}",
        details=(
            "HEX исправлен и сохранён"
            if allow_replace
            else "HEX считан и сохранён"
        ),
        key_id=key_id,
        key_type=key["type_name"],
        printed_number=key["number"],
        hex_value=key["hex_value"],
    )
    return JSONResponse(
        {
            "ok": True,
            "key_id": key_id,
            "hex_value": key["hex_value"],
            "message": "Исправление сохранено" if allow_replace else "Сохранено автоматически",
        }
    )


@router.post("/keys/import")
async def keys_import(request: Request, file: UploadFile = File(...)):
    report = import_keys_file(
        file.filename or "",
        await file.read(),
        created_by=_user_name(request),
    )

    log_event(
        request=request,
        action="import_keys",
        object_type="Файл ключей",
        object_name=file.filename or "Импорт",
        details=(
            f"Типов создано: {report['created_types']}; "
            f"ключей добавлено: {report['added']}; "
            f"обновлено: {report['updated']}; "
            f"дубликатов: {report['duplicates']}; "
            f"ошибок: {report['errors']}"
        ),
        status="success" if report["errors"] == 0 else "warning",
    )

    return _keys_redirect(imported=1, **{
        key: report[key]
        for key in ("created_types", "added", "updated", "duplicates", "errors")
    })


@router.get("/keys/export")
def keys_export():
    workbook = Workbook(write_only=False)
    default_sheet = workbook.active
    workbook.remove(default_sheet)
    used_names: set[str] = set()

    keys_by_type: dict[str, list[dict]] = {}
    for key in get_all_keys_for_export():
        keys_by_type.setdefault(key["type_name"], []).append(key)

    for type_name, items in keys_by_type.items():
        base_name = re.sub(r"[\\/*?:\[\]]", "_", type_name)[:31] or "Без типа"
        sheet_name = base_name
        suffix = 2
        while sheet_name.lower() in used_names:
            marker = f"_{suffix}"
            sheet_name = f"{base_name[:31 - len(marker)]}{marker}"
            suffix += 1
        used_names.add(sheet_name.lower())

        sheet = workbook.create_sheet(sheet_name)
        sheet.append(
            [
                "Номер",
                "HEX",
                "Статус",
                "Комментарий",
                "Дата добавления",
                "Кем добавлен",
            ]
        )
        for key in items:
            sheet.append(
                [
                    key["number"],
                    key["hex_value"],
                    key_status_name(key["status"]),
                    key["note"],
                    key["created_at"],
                    key["created_by"],
                ]
            )
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions

    if not workbook.worksheets:
        workbook.create_sheet("Ключи")

    output = io.BytesIO()
    workbook.save(output)
    output.seek(0)

    return StreamingResponse(
        output,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={
            "Content-Disposition": 'attachment; filename="keys_export.xlsx"'
        },
    )


@router.get("/keys/{key_id}", response_class=HTMLResponse)
def key_detail(request: Request, key_id: int):
    key = get_key(key_id)
    if not key:
        return _keys_redirect(error="Ключ не найден")

    return templates.TemplateResponse(
        "key_detail.html",
        {
            "request": request,
            "key": key,
            "key_types": get_key_types(),
            "key_statuses": KEY_STATUSES,
            "assignments": get_key_assignments(key_id),
            "history": [
                normalize_operation_row(item)
                for item in get_key_history(key_id)
            ],
            "message": request.query_params.get("message", ""),
            "error": request.query_params.get("error", ""),
        },
    )


@router.post("/keys/{key_id}/update")
def key_update_route(
    request: Request,
    key_id: int,
    key_type_id: int = Form(...),
    number: str = Form(...),
    hex_value: str = Form(""),
    note: str = Form(""),
):
    try:
        update_key(
            key_id,
            key_type_id,
            number,
            hex_value,
            note,
        )
    except ValueError as error:
        return RedirectResponse(
            f"/keys/{key_id}?{urlencode({'error': str(error)})}",
            status_code=303,
        )

    key = get_key(key_id)
    log_event(
        request=request,
        action="key_update",
        object_type="Ключ",
        object_name=f"{(key or {}).get('type_name', '')} №{number}",
        details="Карточка ключа обновлена",
        key_id=key_id,
        key_type=(key or {}).get("type_name", ""),
        printed_number=number,
        hex_value=(key or {}).get("hex_value", "-"),
    )
    return RedirectResponse(
        f"/keys/{key_id}?message=Ключ+обновлён",
        status_code=303,
    )


@router.post("/keys/{key_id}/status")
def key_status_route(
    request: Request,
    key_id: int,
    status: str = Form(...),
    note: str = Form(""),
):
    try:
        set_key_status(key_id, status, note)
    except ValueError as error:
        return RedirectResponse(
            f"/keys/{key_id}?{urlencode({'error': str(error)})}",
            status_code=303,
        )

    key = get_key(key_id)
    log_event(
        request=request,
        action="key_status_change",
        object_type="Ключ",
        object_name=(key or {}).get("number") or str(key_id),
        details=f"Новый статус: {key_status_name(status)}",
        key_id=key_id,
        key_type=(key or {}).get("type_name", ""),
        printed_number=(key or {}).get("number", ""),
        hex_value=(key or {}).get("hex_value", "-"),
        comment=note,
    )
    return RedirectResponse(
        f"/keys/{key_id}?message=Статус+обновлён",
        status_code=303,
    )


@router.post("/keys/{key_id}/release")
def key_release_route(
    request: Request,
    key_id: int,
    note: str = Form("Освобождён вручную"),
):
    try:
        release_key(key_id, note)
    except ValueError as error:
        return RedirectResponse(
            f"/keys/{key_id}?{urlencode({'error': str(error)})}",
            status_code=303,
        )

    key = get_key(key_id)
    log_event(
        request=request,
        action="key_release",
        object_type="Ключ",
        object_name=(key or {}).get("number") or str(key_id),
        details=note,
        key_id=key_id,
        key_type=(key or {}).get("type_name", ""),
        printed_number=(key or {}).get("number", ""),
        hex_value=(key or {}).get("hex_value", "-"),
    )
    return RedirectResponse(
        f"/keys/{key_id}?message=Ключ+освобождён",
        status_code=303,
    )
