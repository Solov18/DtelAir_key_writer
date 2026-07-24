from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse

from app.repositories.key_repository import get_key_types
from app.services import (
    find_key,
    find_panels_by_address,
    get_panels,
    is_ambiguous_key,
    write_key_to_panels,
)
from app.templates_config import templates

router = APIRouter()


def normalize_hex(value: str) -> str:
    value = value.strip().upper().replace(" ", "").replace(":", "").replace("-", "")

    if value.startswith("000000") and len(value) == 14:
        value = value[6:]

    return value


def is_hex_like(value: str) -> bool:
    value = normalize_hex(value)

    return len(value) == 8 and all(ch in "0123456789ABCDEF" for ch in value)


def universal_find_key(query: str):
    return find_key(query)


@router.get("/write/manual", response_class=HTMLResponse)
def manual_write_form(
    request: Request,
    key_query: str = "",
    key_type_id: int = 0,
):
    return templates.TemplateResponse(
        "manual_write.html",
        {
            "request": request,
            "key": None,
            "panels": [],
            "query": key_query,
            "key_type_id": key_type_id,
            "key_types": get_key_types(include_archived=False),
            "address": "",
            "apartment": "",
            "error": None,
        },
    )


@router.post("/write/manual/preview", response_class=HTMLResponse)
def manual_write_preview(
    request: Request,
    key_query: str = Form(...),
    address: str = Form(...),
    apartment: str = Form(""),
    key_type_id: int = Form(0),
):
    key = find_key(key_query, key_type_id or None)
    address = address.strip()
    apartment = apartment.strip()
    panels = find_panels_by_address(address)

    error = None

    if is_ambiguous_key(key):
        error = "Номер встречается в нескольких типах. Выберите тип ключа."
        key = None
    elif not key:
        error = "Ключ не найден в базе"
    elif not panels:
        error = "Панели по этому адресу не найдены"
    elif not apartment:
        error = "Укажите квартиру. Без неё запись жильцу выполнять нельзя."

    if panels:
        address = panels[0].get("address") or address

    return templates.TemplateResponse(
        "manual_write.html",
        {
            "request": request,
            "key": key,
            "panels": panels,
            "query": key_query,
            "key_type_id": key_type_id,
            "key_types": get_key_types(include_archived=False),
            "address": address,
            "apartment": apartment,
            "error": error,
        },
    )


@router.post("/write/manual/write", response_class=HTMLResponse)
def manual_write_execute(
    request: Request,
    key_query: str = Form(...),
    address: str = Form(...),
    apartment: str = Form(""),
    inner: int = Form(1),
    panel_ids: list[int] = Form([]),
    key_type_id: int = Form(0),
):
    key = find_key(key_query, key_type_id or None)

    if is_ambiguous_key(key):
        key = None

    panels = get_panels(panel_ids=panel_ids) if panel_ids else []

    all_results = []

    warning = None
    if not key:
        warning = "Ключ не найден или его тип не определён."
    elif not apartment.strip():
        warning = "Квартира не указана. Запись не выполнялась."
    elif not panels:
        warning = "Не выбрана ни одна панель. Запись не выполнялась."

    if key and apartment.strip() and panels:
        all_results.append(
            {
                "key": key,
                "results": write_key_to_panels(
                    "resident_manual",
                    key,
                    panels,
                    flat_num=apartment,
                    inner=inner,
                    address=address,
                    request=request,
                ),
            }
        )
    elif not key:
        all_results.append(
            {
                "key": {
                    "number": key_query,
                    "hex_value": "НЕ НАЙДЕН",
                },
                "results": [],
            }
        )

    return templates.TemplateResponse(
        "write_results.html",
        {
            "request": request,
            "title": "Результат ручной записи ключа",
            "all_results": all_results,
            "result_warning": warning,
            "back_url": "/write/manual",
        },
    )
