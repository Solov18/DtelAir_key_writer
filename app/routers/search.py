from urllib.parse import quote_plus

from fastapi import APIRouter, Request, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from app.services import universal_search
from app.services.search import get_search_suggestions
from app.repositories.key_repository import search_keys_for_selection
from app.templates_config import templates

router = APIRouter()


@router.get("/api/keys/search")
def key_picker_search(
    q: str = Query(""),
    key_type_id: int | None = Query(None, ge=1),
    only_free: bool = Query(False),
    limit: int = Query(12, ge=1, le=20),
):
    items = search_keys_for_selection(
        q,
        key_type_id=key_type_id,
        only_free=only_free,
        limit=limit,
    )
    return {
        "items": [
            {
                "id": item["id"],
                "value": f"{item['type_name']} · №{item['number']} · {item['hex_value']}",
                "label": f"{item['type_name']} · №{item['number']}",
                "meta": f"HEX {item['hex_value']} · "
                        f"{'Свободен' if item['available'] else 'Уже используется'}",
                "number": item["number"],
                "hex": item["hex_value"],
                "type_id": item["type_id"],
                "type": item["type_name"],
                "color": item["type_color"],
                "status": item["status"],
                "status_name": "Свободен" if item["available"] else "Уже используется",
                "available": bool(item["available"]),
                "disabled": not bool(item["available"]),
            }
            for item in items
        ]
    }


@router.get("/api/search/suggestions")
def search_suggestions(
    q: str = Query(""),
    scope: str = Query("universal"),
    limit: int = Query(8, ge=1, le=12),
):
    return {
        "items": get_search_suggestions(
            query=q,
            scope=scope,
            limit=limit,
        )
    }


@router.get("/search", response_class=HTMLResponse)
def search_page(request: Request, q: str = Query("")):
    return templates.TemplateResponse(
        "search.html",
        {
            "request": request,
            "result": universal_search(q) if q.strip() else None,
        },
    )


@router.post("/search", response_class=HTMLResponse)
def search_execute(
    request: Request,
    query: str = Form(...),
):
    return RedirectResponse(
        url=f"/search?q={quote_plus(query.strip())}",
        status_code=303,
    )
