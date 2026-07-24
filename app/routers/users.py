from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from app.repositories.user_repository import (
    get_users,
    get_user_by_login,
    create_user,
    delete_user,
    count_admins,
    change_user_password,
    get_user_stats,
    set_user_active,
    update_user_role,
)
from app.access_control import ROLE_DEFINITIONS, ROLE_ORDER, role_label
from app.services.auth import get_current_user, hash_password, is_admin
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
            "stats": get_user_stats(),
            "roles": ROLE_DEFINITIONS,
            "role_order": ROLE_ORDER,
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

    if len(password) < 8:
        return RedirectResponse("/users?notice=weak_password", status_code=303)

    if role not in ROLE_DEFINITIONS:
        role = "operator"

    if get_user_by_login(login):
        return templates.TemplateResponse(
            "users.html",
            {
                "request": request,
                "users": get_users(),
                "stats": get_user_stats(),
                "roles": ROLE_DEFINITIONS,
                "role_order": ROLE_ORDER,
                "error": f"Пользователь с логином '{login}' уже существует",
            },
            status_code=200,
        )

    create_user(
        full_name=full_name,
        login=login,
        password_hash=hash_password(password),
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
                "stats": get_user_stats(),
                "roles": ROLE_DEFINITIONS,
                "role_order": ROLE_ORDER,
                "error": "Нельзя удалить пользователя, под которым вы сейчас вошли",
            },
            status_code=200,
        )

    if (
        user_to_delete["role"] == "admin"
        and int(user_to_delete.get("active", 1))
        and count_admins() <= 1
    ):
        return templates.TemplateResponse(
            "users.html",
            {
                "request": request,
                "users": users,
                "stats": get_user_stats(),
                "roles": ROLE_DEFINITIONS,
                "role_order": ROLE_ORDER,
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

    if len(password) < 8:
        return RedirectResponse("/users?notice=weak_password", status_code=303)

    change_user_password(
        user_id=user_id,
        password_hash=hash_password(password),
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


@router.post("/users/role")
def users_role(
    request: Request,
    user_id: int = Form(...),
    role: str = Form(...),
):
    current = get_current_user(request)
    if not is_admin(current):
        return RedirectResponse("/", status_code=303)
    user = next(
        (item for item in get_users() if int(item["id"]) == int(user_id)),
        None,
    )
    if not user or role not in ROLE_DEFINITIONS:
        return RedirectResponse("/users?notice=invalid_role", status_code=303)
    if int(user_id) == int(current["id"]) and role != current["role"]:
        return RedirectResponse("/users?notice=self_role", status_code=303)
    if (
        user["role"] == "admin"
        and role != "admin"
        and int(user.get("active", 1))
        and count_admins() <= 1
    ):
        return RedirectResponse("/users?notice=last_admin", status_code=303)
    update_user_role(user_id, role)
    log_event(
        request=request,
        action="user_role_change",
        object_type="Пользователь",
        object_name=user["full_name"],
        status="success",
        details=f"Роль изменена: {role_label(role)}",
    )
    return RedirectResponse("/users?notice=role_updated", status_code=303)


@router.post("/users/active")
def users_active(
    request: Request,
    user_id: int = Form(...),
    active: int = Form(...),
):
    current = get_current_user(request)
    if not is_admin(current):
        return RedirectResponse("/", status_code=303)
    user = next(
        (item for item in get_users() if int(item["id"]) == int(user_id)),
        None,
    )
    if not user:
        return RedirectResponse("/users", status_code=303)
    if int(user_id) == int(current["id"]) and not active:
        return RedirectResponse("/users?notice=self_disable", status_code=303)
    if (
        user["role"] == "admin"
        and int(user.get("active", 1))
        and not active
        and count_admins() <= 1
    ):
        return RedirectResponse("/users?notice=last_admin", status_code=303)
    set_user_active(user_id, bool(active))
    log_event(
        request=request,
        action="user_status_change",
        object_type="Пользователь",
        object_name=user["full_name"],
        status="success",
        details="Доступ включён" if active else "Доступ приостановлен",
    )
    return RedirectResponse("/users?notice=status_updated", status_code=303)
