from fastapi import APIRouter, Request, Form
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


@router.get("/message", response_class=HTMLResponse)
def message_form(request: Request):
    return templates.TemplateResponse(
        "message.html",
        {
            "request": request,
        },
    )


@router.post("/message/preview", response_class=HTMLResponse)
def message_preview(
    request: Request,
    text: str = Form(...),
):
    parsed = parse_message(text)

    keys = []
    for n in parsed["key_numbers"]:
        item = find_key(n)
        ambiguous = is_ambiguous_key(item)
        keys.append(
            {
                "number": n,
                "item": None if ambiguous else item,
                "ambiguous": ambiguous,
                "matches": item.get("matches", []) if ambiguous else [],
            }
        )

    panels = find_panels_by_address(parsed["address"])

    return templates.TemplateResponse(
        "message_preview.html",
        {
            "request": request,
            "text": text,
            "parsed": parsed,
            "keys": keys,
            "panels": panels,
        },
    )


@router.post("/message/write", response_class=HTMLResponse)
def message_write(
    request: Request,
    address: str = Form(""),
    apartment: str = Form(""),
    key_numbers: list[str] = Form([]),
    key_type_ids: list[int] = Form([]),
    panel_ids: list[int] = Form([]),
):
    if panel_ids:
        panels = get_panels(panel_ids=panel_ids)
    else:
        panels = find_panels_by_address(address)

    all_results = []

    for index, n in enumerate(key_numbers):
        n = n.strip()
        if not n:
            continue
        key_type_id = key_type_ids[index] if index < len(key_type_ids) else 0
        item = find_key(n, key_type_id or None)

        if is_ambiguous_key(item):
            item = None

        if item:
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
                    "key": {
                        "number": n,
                        "hex_value": "НЕ НАЙДЕН",
                    },
                    "results": [],
                }
            )

    return templates.TemplateResponse(
        "write_results.html",
        {
            "request": request,
            "title": "Результат записи жильца",
            "all_results": all_results,
        },
    )
