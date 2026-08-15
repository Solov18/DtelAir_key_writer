from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.access_control import has_permission
from app.repositories.role_repository import get_role, get_roles
from app.repositories.user_repository import (
    change_user_password,
    count_admins,
    create_user,
    delete_user,
    get_user_by_login,
    get_user_stats,
    get_users,
    set_user_active,
    update_user,
)
from app.services.audit import log_event
from app.services.auth import get_current_user, hash_password
from app.templates_config import templates

router = APIRouter()


def _can_manage(request: Request) -> bool:
    return has_permission(get_current_user(request), "manage_users")


def _page_context(request: Request, error: str | None = None) -> dict:
    return {
        "request": request,
        "users": get_users(),
        "stats": get_user_stats(),
        "roles": get_roles(),
        "error": error,
    }


@router.get("/users", response_class=HTMLResponse)
def users_page(request: Request):
    if not _can_manage(request):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("users.html", _page_context(request))


@router.post("/users/add")
def users_add(
    request: Request,
    full_name: str = Form(...),
    login: str = Form(...),
    password: str = Form(...),
    role_id: int = Form(...),
):
    if not _can_manage(request):
        return RedirectResponse("/", status_code=303)
    full_name = full_name.strip()
    login = login.strip()
    role = get_role(role_id)
    if not full_name or not login or not role:
        return templates.TemplateResponse(
            "users.html",
            _page_context(request, "Заполните имя, логин и выберите существующую роль."),
        )
    if len(password) < 8:
        return RedirectResponse("/users?notice=weak_password", status_code=303)
    if get_user_by_login(login):
        return templates.TemplateResponse(
            "users.html",
            _page_context(request, f"Пользователь с логином «{login}» уже существует."),
        )
    try:
        create_user(full_name, login, hash_password(password), role["code"])
    except ValueError as error:
        return templates.TemplateResponse(
            "users.html",
            _page_context(request, str(error)),
        )
    log_event(
        request=request,
        action="user_create",
        object_type="Пользователь",
        object_name=full_name,
        status="success",
        details=f"Создан пользователь с логином «{login}», роль: {role['name']}",
    )
    return RedirectResponse("/users?notice=user_created", status_code=303)


@router.post("/users/update")
def users_update(
    request: Request,
    user_id: int = Form(...),
    full_name: str = Form(...),
    login: str = Form(...),
    role_id: int = Form(...),
):
    if not _can_manage(request):
        return RedirectResponse("/", status_code=303)
    current = get_current_user(request)
    user = next((item for item in get_users() if item["id"] == user_id), None)
    role = get_role(role_id)
    full_name = full_name.strip()
    login = login.strip()
    if not user or not role or not full_name or not login:
        return RedirectResponse("/users?notice=invalid_user", status_code=303)
    duplicate = get_user_by_login(login)
    if duplicate and int(duplicate["id"]) != user_id:
        return templates.TemplateResponse(
            "users.html",
            _page_context(request, f"Логин «{login}» уже занят."),
        )
    if user_id == int(current["id"]) and role["code"] != current["role"]:
        return RedirectResponse("/users?notice=self_role", status_code=303)
    if (
        user["role"] == "admin"
        and role["code"] != "admin"
        and bool(user["active"])
        and count_admins() <= 1
    ):
        return RedirectResponse("/users?notice=last_admin", status_code=303)
    try:
        update_user(user_id, full_name, login, role_id)
    except ValueError as error:
        return templates.TemplateResponse(
            "users.html",
            _page_context(request, str(error)),
        )
    log_event(
        request=request,
        action="user_update",
        object_type="Пользователь",
        object_name=full_name,
        status="success",
        details=f"Обновлены имя, логин и роль пользователя; роль: {role['name']}",
    )
    return RedirectResponse("/users?notice=user_updated", status_code=303)


@router.post("/users/password")
def users_password(
    request: Request,
    user_id: int = Form(...),
    password: str = Form(...),
):
    if not _can_manage(request):
        return RedirectResponse("/", status_code=303)
    user = next((item for item in get_users() if item["id"] == user_id), None)
    if not user:
        return RedirectResponse("/users?notice=invalid_user", status_code=303)
    if len(password) < 8:
        return RedirectResponse("/users?notice=weak_password", status_code=303)
    change_user_password(user_id, hash_password(password))
    log_event(
        request=request,
        action="user_password_change",
        object_type="Пользователь",
        object_name=user["full_name"],
        status="success",
        details="Пароль пользователя изменён",
    )
    return RedirectResponse("/users?notice=password_updated", status_code=303)


@router.post("/users/active")
def users_active(
    request: Request,
    user_id: int = Form(...),
    active: int = Form(...),
):
    if not _can_manage(request):
        return RedirectResponse("/", status_code=303)
    current = get_current_user(request)
    user = next((item for item in get_users() if item["id"] == user_id), None)
    enabled = bool(active)
    if not user:
        return RedirectResponse("/users?notice=invalid_user", status_code=303)
    if user_id == int(current["id"]) and not enabled:
        return RedirectResponse("/users?notice=self_disable", status_code=303)
    if user["role"] == "admin" and bool(user["active"]) and not enabled and count_admins() <= 1:
        return RedirectResponse("/users?notice=last_admin", status_code=303)
    try:
        set_user_active(user_id, enabled)
    except ValueError:
        return RedirectResponse("/users?notice=last_admin", status_code=303)
    log_event(
        request=request,
        action="user_status_change",
        object_type="Пользователь",
        object_name=user["full_name"],
        status="success",
        details="Доступ включён" if enabled else "Доступ приостановлен",
    )
    return RedirectResponse("/users?notice=status_updated", status_code=303)


@router.post("/users/delete")
def users_delete(request: Request, user_id: int = Form(...)):
    if not _can_manage(request):
        return RedirectResponse("/", status_code=303)
    current = get_current_user(request)
    user = next((item for item in get_users() if item["id"] == user_id), None)
    if not user:
        return RedirectResponse("/users?notice=invalid_user", status_code=303)
    if user_id == int(current["id"]):
        return RedirectResponse("/users?notice=self_delete", status_code=303)
    if user["role"] == "admin" and bool(user["active"]) and count_admins() <= 1:
        return RedirectResponse("/users?notice=last_admin", status_code=303)
    try:
        delete_user(user_id)
    except ValueError:
        return RedirectResponse("/users?notice=last_admin", status_code=303)
    log_event(
        request=request,
        action="user_delete",
        object_type="Пользователь",
        object_name=user["full_name"],
        status="success",
        details=f"Удалена учётная запись с логином «{user['login']}»",
    )
    return RedirectResponse("/users?notice=user_deleted", status_code=303)
