from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse

from app.repositories.key_repository import get_key_types
from app.services import (
    find_key,
    find_panels_by_address,
    get_panels,
    is_ambiguous_key,
    write_key_to_panels,
    get_key_write_context,
    key_write_state_token,
    resolve_key_write_decision,
    KeyWriteResult,
)
from app.response_utils import async_document_response
from app.services.key_lifecycle import reassign_key as reassign_key_lifecycle
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
            "write_context": {},
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
    elif not key or not key.get("id"):
        error = "Ключ не найден в базе"
        key = None
    elif not panels:
        error = "Панели по этому адресу не найдены"
    elif not apartment:
        error = "Укажите квартиру. Без неё запись жильцу выполнять нельзя."

    if panels:
        address = panels[0].get("address") or address

    write_context = get_key_write_context(key["id"], panels) if key and key.get("id") else {}

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
            "write_context": write_context,
            "key_state_token": key_write_state_token(write_context) if key else "",
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
    automatic_panel_ids: list[int] = Form([]),
    manual_panel_ids: list[int] = Form([]),
    key_type_id: int = Form(0),
    occupied_action: str = Form(""),
    key_state_token: str = Form(""),
):
    key = find_key(key_query, key_type_id or None)

    if is_ambiguous_key(key):
        key = None

    automatic_panel_ids = automatic_panel_ids if isinstance(automatic_panel_ids, list) else []
    manual_panel_ids = manual_panel_ids if isinstance(manual_panel_ids, list) else []
    panel_ids = panel_ids if isinstance(panel_ids, list) else []
    panel_ids = list(dict.fromkeys(int(value) for value in panel_ids))
    selected_panel_ids = set(panel_ids)
    automatic_panel_ids = list(dict.fromkeys(
        int(value) for value in automatic_panel_ids
        if int(value) in selected_panel_ids
    ))
    automatic_panel_set = set(automatic_panel_ids)
    manual_panel_ids = list(dict.fromkeys(
        int(value) for value in manual_panel_ids
        if int(value) in selected_panel_ids and int(value) not in automatic_panel_set
    ))
    panels = get_panels(panel_ids=panel_ids) if panel_ids else []

    all_results = []

    warning = None
    if key and not key.get("id"):
        key = None
    context = get_key_write_context(key["id"], panels) if key else {}
    decision = resolve_key_write_decision(context, occupied_action)
    if not key:
        warning = "Ключ не найден или его тип не определён."
    elif not apartment.strip():
        warning = "Квартира не указана. Запись не выполнялась."
    elif not panels:
        warning = "Не выбрана ни одна панель. Запись не выполнялась."
    elif isinstance(key_state_token, str) and key_state_token and key_write_state_token(context) != key_state_token:
        warning = "Состояние ключа изменилось. Проверьте данные повторно перед записью."
    elif decision["action_required"]:
        warning = "Ключ уже используется. Выберите: переназначить его или только добавить на выбранные панели."

    state_is_current = not (
        isinstance(key_state_token, str)
        and key_state_token
        and key_write_state_token(context) != key_state_token
    )
    if key and apartment.strip() and panels and state_is_current and not decision["action_required"]:
        def write_target(_snapshot=None):
            return write_key_to_panels(
                "resident_manual", key, panels, flat_num=apartment, inner=inner,
                address=address, request=request, assignment_type="resident",
                assignment_policy=decision["assignment_policy"],
                known_panel_ids=(set() if decision["action"] == "reassign" else decision["known_panel_ids"]),
                write_option=decision["write_option"],
                previous_assignment=decision["previous_assignment"],
                automatic_panel_ids=set(automatic_panel_ids),
                manual_panel_ids=set(manual_panel_ids),
            )

        if decision["action"] == "reassign":
            lifecycle_result = reassign_key_lifecycle(
                int(key["id"]), write_callback=write_target,
                reason=f"Переназначение на {address}, кв. {apartment}", request=request,
            )
            legacy_results = lifecycle_result.get("write") or lifecycle_result["release"].get("results", [])
            if lifecycle_result.get("write") is None:
                warning = "Переназначение не выполнено: старый доступ удалён не со всех панелей."
        else:
            legacy_results = write_target()
        write_result = KeyWriteResult.from_writer(key.get("id"), legacy_results)
        all_results.append(
            {
                "key": key,
                "results": write_result.to_legacy_results(),
                "write_result": write_result,
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

    response = templates.TemplateResponse(
        "write_results.html",
        {
            "request": request,
            "title": "Результат ручной записи ключа",
            "all_results": all_results,
            "result_warning": warning,
            "back_url": "/write/manual",
        },
    )
    return async_document_response(request, response, url="/write/manual")
