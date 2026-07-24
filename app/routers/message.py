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

    back_url = (
        f"/message?{urlencode({'text': source_text})}"
        if source_text
        else "/message"
    )
    return templates.TemplateResponse(
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
