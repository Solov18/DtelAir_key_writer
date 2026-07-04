from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from app.repositories.user_repository import (
    get_users,
    get_user_by_login,
    create_user,
    delete_user,
    count_admins,
    change_user_password,
)
from app.services.auth import get_current_user, is_admin
from app.services.audit import log_event
from app.templates_config import templates

router = APIRouter()


@router.get("/users", response_class=HTMLResponse)
def users_page(request: Request):
    current_user = get_current_user(request)

    if not is_admin(current_user):
        return RedirectResponse("/", status_code=303)

    return templates.TemplateResponse(
        "users.html",
        {
            "request": request,
            "users": get_users(),
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

    full_name = full_name.strip()
    login = login.strip()

    if role not in ("admin", "operator"):
        role = "operator"

    if get_user_by_login(login):
        return templates.TemplateResponse(
            "users.html",
            {
                "request": request,
                "users": get_users(),
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
        action="user_create",
        object_type="Пользователь",
        object_name=full_name,
        status="success",
        details=f"Создан пользователь '{login}' с ролью '{role}'",
    )

    return RedirectResponse("/users", status_code=303)


@router.post("/users/delete")
def users_delete(
    request: Request,
    user_id: int = Form(...),
):
    current_user = get_current_user(request)

    if not is_admin(current_user):
        return RedirectResponse("/", status_code=303)

    users = get_users()

    user_to_delete = next(
        (u for u in users if int(u["id"]) == int(user_id)),
        None,
    )

    if not user_to_delete:
        return RedirectResponse("/users", status_code=303)

    if int(user_id) == int(current_user["id"]):
        return templates.TemplateResponse(
            "users.html",
            {
                "request": request,
                "users": users,
                "error": "Нельзя удалить пользователя, под которым вы сейчас вошли",
            },
            status_code=200,
        )

    if user_to_delete["role"] == "admin" and count_admins() <= 1:
        return templates.TemplateResponse(
            "users.html",
            {
                "request": request,
                "users": users,
                "error": "Нельзя удалить последнего администратора",
            },
            status_code=200,
        )

    delete_user(user_id)

    log_event(
        request=request,
        action="user_delete",
        object_type="Пользователь",
        object_name=user_to_delete["full_name"],
        status="success",
        details=f"Удалён пользователь '{user_to_delete['login']}'",
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

    users = get_users()

    user = next(
        (u for u in users if int(u["id"]) == int(user_id)),
        None,
    )

    if not user:
        return RedirectResponse("/users", status_code=303)

    change_user_password(
        user_id=user_id,
        password_hash=password,
    )

    log_event(
        request=request,
        action="user_password_change",
        object_type="Пользователь",
        object_name=user["full_name"],
        status="success",
        details="Изменён пароль пользователя",
    )

    return RedirectResponse("/users", status_code=303)