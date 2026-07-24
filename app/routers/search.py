from urllib.parse import quote_plus

from fastapi import APIRouter, Request, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from app.services import universal_search
from app.services.search import get_search_suggestions
from app.templates_config import templates

router = APIRouter()


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
