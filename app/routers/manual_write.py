from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse

from app.db import db
from app.services import (
    find_panels_by_address,
    get_panels,
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
    q = query.strip()

    if not q:
        return None

    hex_candidate = normalize_hex(q)

    with db() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM keys
            WHERE number = ?
            LIMIT 1
            """,
            (q,),
        ).fetchone()

        if row:
            return dict(row)

        row = conn.execute(
            """
            SELECT *
            FROM keys
            WHERE number = ?
            LIMIT 1
            """,
            (q.replace(" ", ""),),
        ).fetchone()

        if row:
            return dict(row)

        if is_hex_like(q):
            row = conn.execute(
                """
                SELECT *
                FROM keys
                WHERE UPPER(hex_value) = ?
                LIMIT 1
                """,
                (hex_candidate,),
            ).fetchone()

            if row:
                return dict(row)

    return None


@router.get("/write/manual", response_class=HTMLResponse)
def manual_write_form(request: Request):
    return templates.TemplateResponse(
        "manual_write.html",
        {
            "request": request,
            "key": None,
            "panels": [],
            "query": "",
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
):
    key = universal_find_key(key_query)
    panels = find_panels_by_address(address)

    error = None

    if not key:
        error = "Ключ не найден в базе"
    elif not panels:
        error = "Панели по этому адресу не найдены"

    return templates.TemplateResponse(
        "manual_write.html",
        {
            "request": request,
            "key": key,
            "panels": panels,
            "query": key_query,
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
):
    key = universal_find_key(key_query)

    if panel_ids:
        panels = get_panels(panel_ids=panel_ids)
    else:
        panels = find_panels_by_address(address)

    all_results = []

    if key:
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
                ),
            }
        )
    else:
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
        },
    )