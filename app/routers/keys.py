from fastapi import APIRouter, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse

from app.services import import_keys_file
from app.templates_config import templates
from app.repositories.key_repository import get_recent_keys

router = APIRouter()


@router.get("/keys", response_class=HTMLResponse)
def keys_page(request: Request):
    return templates.TemplateResponse(
        "keys.html",
        {
            "request": request,
            "keys": get_recent_keys(),
        },
    )


@router.post("/keys/import")
async def keys_import(file: UploadFile = File(...)):
    count = import_keys_file(
        file.filename,
        await file.read(),
    )

    return RedirectResponse(
        f"/keys?imported={count}",
        status_code=303,
    )