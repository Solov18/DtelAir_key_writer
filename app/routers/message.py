import re
from urllib.parse import urlencode

from fastapi import APIRouter, Request, Form, Query
from fastapi.responses import HTMLResponse

from app.services import (
    parse_message,
    find_key,
    find_panels_by_address,
    get_panels,
    is_ambiguous_key,
    write_key_to_panels,
)
from app.response_utils import async_document_response
from app.repositories.key_repository import get_key_write_contexts
from app.templates_config import templates

router = APIRouter()


def _key_values_from_override(value: str) -> list[str]:
    result: list[str] = []
    for item in re.findall(r"[0-9A-Fa-f]{4,16}", value or ""):
        normalized = item.upper()
        if normalized not in result:
            result.append(normalized)
    return result


def _build_key_rows(numbers: list[str]) -> list[dict]:
    keys: list[dict] = []
    for number in numbers:
        item = find_key(number)
        ambiguous = is_ambiguous_key(item)
        keys.append(
            {
                "number": number,
                "item": None if ambiguous else item,
                "ambiguous": ambiguous,
                "matches": item.get("matches", []) if ambiguous else [],
            }
        )
    return keys


def _write_context_description(context: dict) -> str:
    parts = [context.get("assignment_type_name") or "Назначение"]
    if context.get("assignment_address"):
        parts.append(context["assignment_address"])
    apartment = (context.get("assignment_apartment") or "").strip()
    if apartment:
        parts.append(f"кв. {apartment}")
    if context.get("owner_name"):
        parts.append(context["owner_name"])
    return ", ".join(parts)


def _enrich_key_write_rows(keys: list[dict], panels: list[dict]) -> bool:
    key_ids = [row["item"]["id"] for row in keys if row.get("item")]
    contexts = get_key_write_contexts(key_ids)
    selected_panel_ids = {int(panel["id"]) for panel in panels}
    has_used_keys = False
    for row in keys:
        item = row.get("item") or {}
        context = contexts.get(int(item.get("id") or 0), {})
        known_panel_ids = {int(value) for value in context.get("panel_ids", [])}
        selected_known_ids = known_panel_ids & selected_panel_ids
        is_used = bool(context.get("is_used"))
        has_used_keys = has_used_keys or is_used
        if row.get("ambiguous"):
            write_state = "conflict"
        elif not item:
            write_state = "missing"
        elif selected_panel_ids and selected_known_ids == selected_panel_ids:
            write_state = "all_selected"
        elif selected_known_ids:
            write_state = "partial_selected"
        elif is_used:
            write_state = "used"
        else:
            write_state = "free"
        row["write_context"] = {
            **context,
            "is_used": is_used,
            "write_state": write_state,
            "description": _write_context_description(context) if is_used else "",
            "known_panel_ids_csv": ",".join(
                str(value) for value in sorted(known_panel_ids)
            ),
        }
    return has_used_keys


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

    keys = _build_key_rows(parsed["key_numbers"])
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

    has_used_keys = _enrich_key_write_rows(keys, panels)

    missing_keys = [
        item["number"]
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
                panels
                and keys
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
    occupied_action: str = Form(""),
):
    # Важная защита: запись выполняется только на явно выбранные панели.
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
            context = get_key_write_contexts([item["id"]]).get(item["id"], {})
            is_used = bool(context.get("is_used"))
            if is_used and occupied_action not in {"reassign", "add_panels"}:
                all_results.append(
                    {
                        "key": item,
                        "results": [],
                        "action_required": True,
                    }
                )
                continue
            assignment_policy = (
                "preserve"
                if is_used and occupied_action == "add_panels"
                else "replace"
            )
            write_option = (
                "add_selected_panels"
                if assignment_policy == "preserve"
                else "reassign_to_new_address"
                if is_used
                else "write_free_key"
            )
            all_results.append(
                {
                    "key": item,
                    "results": write_key_to_panels(
                        "message",
                        item,
                        panels,
                        flat_num=apartment,
                        inner=1,
                        address=address,
                        request=request,
                        assignment_type="resident",
                        assignment_policy=assignment_policy,
                        known_panel_ids=set(context.get("panel_ids", [])),
                        write_option=write_option,
                        previous_assignment=_write_context_description(context),
                    ),
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
