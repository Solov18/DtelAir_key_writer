from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse

from app.services import universal_search
from app.templates_config import templates

router = APIRouter()


@router.get("/search", response_class=HTMLResponse)
def search_page(request: Request):
    return templates.TemplateResponse(
        "search.html",
        {
            "request": request,
            "result": None,
        },
    )


@router.post("/search", response_class=HTMLResponse)
def search_execute(
    request: Request,
    query: str = Form(...),
):
    result = universal_search(query)

    return templates.TemplateResponse(
        "search.html",
        {
            "request": request,
            "result": result,
        },
    )
