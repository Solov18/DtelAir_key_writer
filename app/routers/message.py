import re
from urllib.parse import urlencode

from fastapi import APIRouter, Request, Form, Query
from fastapi.responses import HTMLResponse, JSONResponse

from app.services import (
    parse_message,
    find_key,
    find_panels_by_address,
    get_panels,
    is_ambiguous_key,
    write_key_to_panels,
    enrich_key_write_rows,
    get_key_write_context,
    resolve_key_write_decision,
    KeyWriteResult,
)
from app.response_utils import async_document_response
from app.repositories.panel_repository import normalize_panel_row
from app.services.panel_search import PanelSearchProfile, PanelSearchService
from app.templates_config import templates

router = APIRouter()


@router.get("/message/panels/search", response_class=JSONResponse)
def message_panel_search(
    query: str = Query("", max_length=160),
):
    """Search the complete panel registry without exposing API credentials."""
    if len(query.strip()) < 2:
        return {"items": [], "total": 0}

    page = PanelSearchService.search_page(
        query,
        profile=PanelSearchProfile.PICKER_ALL,
        scope="all",
        limit=60,
    )
    items = []
    for result in page.items:
        panel = normalize_panel_row(
            {
                "id": result.id,
                "address": result.address,
                "entrance": result.entrance,
                "name": result.point_name,
                "mac": result.mac,
                "ip": result.ip,
                "enabled": 1 if result.active else 0,
                "api_status": result.status,
            }
        )
        has_mac = bool((panel.get("mac") or "").strip())
        enabled = bool(panel.get("enabled"))
        items.append(
            {
                "id": int(panel["id"]),
                "address": panel.get("address") or "",
                "entrance": panel.get("entrance") or "",
                "name": panel.get("name") or "",
                "mac": panel.get("mac") or "",
                "status_name": panel.get("status_name") or "Не проверена",
                "status_tone": panel.get("status_tone") or "muted",
                "selectable": enabled and has_mac,
                "unavailable_reason": (
                    "Панель отключена" if not enabled
                    else "Не указан MAC" if not has_mac
                    else ""
                ),
            }
        )
    return {"items": items, "total": page.total}


def _key_values_from_override(value: str) -> list[str]:
    result: list[str] = []
    for item in re.findall(r"[0-9A-Fa-f]{4,16}", value or ""):
        normalized = item.upper()
        if normalized not in result:
            result.append(normalized)
    return result


def _build_key_rows(requests: list[dict] | list[str]) -> list[dict]:
    keys: list[dict] = []
    for request in requests:
        if isinstance(request, str):
            request = {"number": request, "type_id": None, "type_name": "", "type_text": ""}
        number = str(request.get("number") or "").strip()
        type_id = request.get("type_id")
        lookup_value = str(request.get("hex_value") or number).strip()
        item = find_key(lookup_value, int(type_id) if type_id else None)
        ambiguous = is_ambiguous_key(item)
        identity_conflict = bool(
            item
            and not ambiguous
            and request.get("hex_value")
            and number
            and str(item.get("number") or "").casefold() != number.casefold()
        )
        keys.append(
            {
                "number": number,
                "requested_type_id": int(type_id) if type_id else None,
                "requested_type_name": request.get("type_name") or "",
                "requested_type_text": request.get("type_text") or "",
                "requested_hex": request.get("hex_value") or "",
                "item": None if ambiguous else item,
                "ambiguous": ambiguous,
                "identity_conflict": identity_conflict,
                "matches": item.get("matches", []) if ambiguous else [],
            }
        )
    return keys


@router.get("/message", response_class=HTMLResponse)
def message_form(
    request: Request,
    text: str = Query(""),
):
    return templates.TemplateResponse(
        "message.html",
        {
            "request": request,
            "text": text,
        },
    )


@router.post("/message/preview", response_class=HTMLResponse)
def message_preview(
    request: Request,
    text: str = Form(...),
    address_override: str = Form(""),
    apartment_override: str = Form(""),
    entrance_override: str = Form(""),
    key_numbers_override: str = Form(""),
):
    parsed = parse_message(text)

    if address_override.strip():
        parsed["address"] = address_override.strip()
        parsed["address_status"] = "confirmed"
    if apartment_override.strip():
        parsed["apartment"] = apartment_override.strip()
    if entrance_override.strip():
        parsed["entrance"] = entrance_override.strip()
    if key_numbers_override.strip():
        parsed["key_numbers"] = _key_values_from_override(
            key_numbers_override
        )
        parsed["key_requests"] = [
            {"number": value, "type_id": None, "type_name": "", "type_text": ""}
            for value in parsed["key_numbers"]
        ]

    keys = _build_key_rows(parsed.get("key_requests") or parsed["key_numbers"])
    panels = (
        find_panels_by_address(parsed["address"])
        if parsed["address"]
        else []
    )
    if panels:
        canonical_addresses = {
            (panel.get("address") or "").strip()
            for panel in panels
            if (panel.get("address") or "").strip()
        }
        if len(canonical_addresses) == 1:
            parsed["address"] = canonical_addresses.pop()

    has_used_keys = enrich_key_write_rows(keys, panels)

    missing_keys = [
        " ".join(filter(None, [item.get("requested_type_name"), f"№{item['number']}"]))
        for item in keys
        if not item["item"] and not item["ambiguous"]
    ]
    ambiguous_keys = [
        item["number"]
        for item in keys
        if item["ambiguous"]
    ]

    warnings: list[str] = []
    if not parsed["address"]:
        if parsed["address_candidates"]:
            warnings.append(
                "Адрес распознан неоднозначно. Выберите похожий вариант ниже."
            )
        else:
            warnings.append(
                "Адрес не найден в базе панелей. Введите его вручную."
            )
    elif not panels:
        warnings.append(
            "Для выбранного адреса панели не найдены. Выберите подсказку из базы."
        )
    if not parsed["apartment"]:
        warnings.append("Квартира не распознана — укажите её перед записью.")
    if not keys:
        warnings.append("Номера ключей не распознаны.")
    if missing_keys:
        warnings.append(
            "В базе нет считанных ключей: " + ", ".join(missing_keys)
        )
    if ambiguous_keys:
        warnings.append(
            "Для номеров "
            + ", ".join(ambiguous_keys)
            + " найдено несколько типов. Выберите тип ключа."
        )
    if has_used_keys:
        warnings.append(
            "Один или несколько ключей уже используются. Проверьте текущее "
            "назначение и выберите: переназначить ключ либо только добавить "
            "его на выбранные панели."
        )

    return templates.TemplateResponse(
        "message_preview.html",
        {
            "request": request,
            "text": text,
            "back_url": f"/message?{urlencode({'text': text})}",
            "parsed": parsed,
            "keys": keys,
            "panels": panels,
            "warnings": warnings,
            "missing_keys": missing_keys,
            "ambiguous_keys": ambiguous_keys,
            "can_write": bool(
                keys
                and not missing_keys
                and parsed["apartment"]
            ),
            "has_unresolved_types": bool(ambiguous_keys),
            "has_used_keys": has_used_keys,
        },
    )


@router.post("/message/write", response_class=HTMLResponse)
def message_write(
    request: Request,
    address: str = Form(""),
    apartment: str = Form(""),
    source_text: str = Form(""),
    key_numbers: list[str] = Form([]),
    key_type_ids: list[int] = Form([]),
    panel_ids: list[int] = Form([]),
    automatic_panel_ids: list[int] = Form([]),
    manual_panel_ids: list[int] = Form([]),
    occupied_action: str = Form(""),
):
    # Важная защита: запись выполняется только на явно выбранные панели.
    automatic_panel_ids = automatic_panel_ids if isinstance(automatic_panel_ids, list) else []
    manual_panel_ids = manual_panel_ids if isinstance(manual_panel_ids, list) else []
    panel_ids = list(dict.fromkeys(int(value) for value in panel_ids))
    selected_panel_ids = set(panel_ids)
    automatic_panel_ids = list(dict.fromkeys(
        int(value) for value in automatic_panel_ids if int(value) in selected_panel_ids
    ))
    automatic_panel_set = set(automatic_panel_ids)
    manual_panel_ids = list(dict.fromkeys(
        int(value) for value in manual_panel_ids
        if int(value) in selected_panel_ids and int(value) not in automatic_panel_set
    ))
    panels = get_panels(panel_ids=panel_ids) if panel_ids else []
    all_results = []

    for index, number in enumerate(key_numbers):
        number = number.strip()
        if not number:
            continue
        key_type_id = key_type_ids[index] if index < len(key_type_ids) else 0
        item = find_key(number, key_type_id or None)
        if is_ambiguous_key(item):
            item = None

        if item and panels and apartment:
            context = get_key_write_context(item["id"], panels)
            decision = resolve_key_write_decision(context, occupied_action)
            if decision["action_required"]:
                all_results.append(
                    {
                        "key": item,
                        "results": [],
                        "action_required": True,
                    }
                )
                continue
            legacy_results = write_key_to_panels(
                "message",
                item,
                panels,
                flat_num=apartment,
                inner=1,
                address=address,
                request=request,
                assignment_type="resident",
                assignment_policy=decision["assignment_policy"],
                known_panel_ids=decision["known_panel_ids"],
                write_option=decision["write_option"],
                previous_assignment=decision["previous_assignment"],
                automatic_panel_ids=set(automatic_panel_ids),
                manual_panel_ids=set(manual_panel_ids),
            )
            write_result = KeyWriteResult.from_writer(item.get("id"), legacy_results)
            all_results.append(
                {
                    "key": item,
                    "results": write_result.to_legacy_results(),
                    "write_result": write_result,
                }
            )
        else:
            all_results.append(
                {
                    "key": item
                    or {
                        "number": number,
                        "hex_value": "НЕ НАЙДЕН",
                    },
                    "results": [],
                }
            )

    result_warning = ""
    if not panel_ids:
        result_warning = (
            "Запись не выполнялась: не выбрана ни одна панель."
        )
    elif not apartment:
        result_warning = (
            "Запись не выполнялась: не указана квартира."
        )
    elif not all_results:
        result_warning = (
            "Запись не выполнялась: нет подходящих ключей."
        )
    elif any(result.get("action_required") for result in all_results):
        result_warning = (
            "Запись не выполнялась для занятого ключа: сначала выберите способ "
            "обработки текущего назначения."
        )

    back_url = (
        f"/message?{urlencode({'text': source_text})}"
        if source_text
        else "/message"
    )
    response = templates.TemplateResponse(
        "write_results.html",
        {
            "request": request,
            "title": "Результат записи жильца",
            "all_results": all_results,
            "message_flow": True,
            "result_warning": result_warning,
            "back_url": back_url,
            "new_message_url": "/message",
        },
    )
    return async_document_response(request, response, url="/message")
