from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from app.services.auth import authenticate_user, get_current_user
from app.templates_config import templates

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    current_user = get_current_user(request)

    if current_user:
        return RedirectResponse("/", status_code=303)

    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "error": "",
        },
    )


@router.post("/login")
def login(
    request: Request,
    login: str = Form(...),
    password: str = Form(...),
):
    user = authenticate_user(login, password)

    if not user:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "Неверный логин или пароль",
            },
            status_code=401,
        )

    request.session["user_id"] = user["id"]

    request.session["user"] = {
        "id": user["id"],
        "full_name": user["full_name"],
        "login": user["login"],
        "role": user["role"],
    }

    return RedirectResponse("/", status_code=303)


@router.get("/logout")
def logout(request: Request):
    request.session.clear()

    return RedirectResponse("/login", status_code=303)