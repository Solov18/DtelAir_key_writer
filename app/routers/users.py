from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from app.services.audit import log_event

from app.repositories.user_repository import (
    get_users,
    get_user_by_login,
    create_user,
    disable_user,
    enable_user,
    change_user_password,
)
from app.services.auth import get_current_user, is_admin
from app.templates_config import templates

router = APIRouter()


@router.get("/users", response_class=HTMLResponse)
def users_page(request: Request):
    current_user = get_current_user(request)

    if not is_admin(current_user):
        return RedirectResponse("/", status_code=303)

    users = get_users()

    return templates.TemplateResponse(
        "users.html",
        {
            "request": request,
            "users": users,
        },
    )


@router.post("/users/add")
def users_add(
    request: Request,
    full_name: str = Form(...),
    login: str = Form(...),
    password: str = Form(...),
    role: str = Form("operator"),
):
    current_user = get_current_user(request)

    if not is_admin(current_user):
        return RedirectResponse("/", status_code=303)

    login = login.strip()

    if role not in ("admin", "operator"):
        role = "operator"

    if get_user_by_login(login):
        users = get_users()

        return templates.TemplateResponse(
            "users.html",
            {
                "request": request,
                "users": users,
                "error": f"Пользователь с логином '{login}' уже существует",
            },
            status_code=200,
        )

    create_user(
        full_name=full_name,
        login=login,
        password_hash=password,
        role=role,
    )

    log_event(
        request=request,
        mode="user_create",
        status="success",
        response=f"Создан пользователь: {full_name.strip()} ({role})",
    )

    return RedirectResponse("/users", status_code=303)



@router.post("/users/disable")
def users_disable(
    request: Request,
    user_id: int = Form(...),
):
    current_user = get_current_user(request)

    if not is_admin(current_user):
        return RedirectResponse("/", status_code=303)

    if int(user_id) == int(current_user["id"]):
        users = get_users()

        return templates.TemplateResponse(
            "users.html",
            {
                "request": request,
                "users": users,
                "error": "Нельзя отключить пользователя, под которым вы сейчас вошли",
            },
            status_code=200,
        )

    disable_user(user_id)

    log_event(
        request=request,
        mode="user_disable",
        status="success",
        response=f"Отключён пользователь ID {user_id}",
    )

    return RedirectResponse("/users", status_code=303)


@router.post("/users/enable")
def users_enable(
    request: Request,
    user_id: int = Form(...),
):
    current_user = get_current_user(request)

    if not is_admin(current_user):
        return RedirectResponse("/", status_code=303)

    enable_user(user_id)

    log_event(
        request=request,
        mode="user_enable",
        status="success",
        response=f"Включён пользователь ID {user_id}",
    )

    return RedirectResponse("/users", status_code=303)


@router.post("/users/password")
def users_password(
    request: Request,
    user_id: int = Form(...),
    password: str = Form(...),
):
    current_user = get_current_user(request)

    if not is_admin(current_user):
        return RedirectResponse("/", status_code=303)

    change_user_password(
        user_id=user_id,
        password_hash=password,
    )

    log_event(
        request=request,
        mode="user_password_change",
        status="success",
        response=f"Сменён пароль пользователя ID {user_id}",
    )

    return RedirectResponse("/users", status_code=303)