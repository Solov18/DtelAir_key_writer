from urllib.parse import quote_plus

from fastapi import APIRouter, Request, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from app.services import universal_search
from app.services.search import get_search_suggestions
from app.repositories.key_repository import search_keys_for_selection
from app.services.panel_search import PanelSearchProfile, PanelSearchService
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


@router.get("/api/panels/search")
def panel_picker_search(
    q: str = Query("", max_length=160),
    scope: str = Query("all", pattern="^(all|uk)$"),
    group_id: int | None = Query(None, ge=1),
    active_only: bool = Query(False),
    exact_address: str = Query("", max_length=200),
    limit: int = Query(20, ge=1, le=100),
):
    """Neutral read-only panel search; no credentials or write state exposed."""
    if len(q.strip()) < 2:
        return {"items": [], "total": 0}
    page = PanelSearchService.search_page(
        q,
        profile=(
            PanelSearchProfile.PICKER_UK
            if scope == "uk"
            else PanelSearchProfile.PICKER_ALL
        ),
        scope=scope,
        group_id=group_id,
        active_only=active_only,
        exact_address=exact_address,
        limit=limit,
    )
    return {
        "items": [item.as_dict() for item in page.items],
        "total": page.total,
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
