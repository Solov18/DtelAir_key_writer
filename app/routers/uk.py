from urllib.parse import urlencode

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.access_control import has_permission
from app.repositories.log_repository import normalize_operation_row
from app.repositories.panel_repository import get_panel_by_id
from app.repositories.uk_repository import (
    add_panel,
    archive_group,
    get_available_key_types,
    get_available_keys,
    get_available_panels,
    get_group,
    get_group_credentials,
    get_group_keys,
    get_group_operations,
    get_group_page,
    get_group_panels,
    get_group_statistics,
    search_group_panels,
    get_issue,
    get_issue_programmings,
    remove_panel,
    save_group,
    update_group,
    update_panel_link,
)
from app.services.audit import log_event
from app.services.auth import get_current_user
from app.services.uk_keys import (
    add_master_panel,
    issue_key,
    remove_from_crm,
    retry_programming,
    unlink_accounting,
)
from app.templates_config import templates


router = APIRouter()


def _is_admin(request: Request) -> bool:
    return has_permission(get_current_user(request), "manage_uk")


def _user_name(request: Request) -> str:
    user = request.session.get("user", {})
    return user.get("full_name") or user.get("login") or "Система"


def _redirect(group_id: int | None = None, **params) -> RedirectResponse:
    if group_id:
        path = f"/uk/{group_id}"
    else:
        path = "/uk"
    clean = {key: value for key, value in params.items() if value not in (None, "")}
    query = f"?{urlencode(clean)}" if clean else ""
    return RedirectResponse(f"{path}{query}", status_code=303)


def _decorate_issues(group_id: int, *, include_closed: bool = False) -> list[dict]:
    issues = get_group_keys(group_id, include_closed=include_closed)
    for issue in issues:
        issue["programmings"] = get_issue_programmings(
            int(issue["issue_id"]),
            include_inactive=True,
        )
        issue["active_programmings"] = [
            item for item in issue["programmings"] if item["active"]
        ]
        issue["is_master"] = len(issue["active_programmings"]) > 1
    return issues


@router.get("/uk", response_class=HTMLResponse)
def uk_page(
    request: Request,
    q: str = Query(""),
    page: int = Query(1, ge=1),
    selected_group_id: int = Query(0, ge=0),
    notice: str = Query(""),
):
    group_page = get_group_page(query=q, page=page, page_size=20)
    selected_group = get_group(selected_group_id) if selected_group_id else None
    if not selected_group and group_page["items"]:
        selected_group = get_group(int(group_page["items"][0]["id"]))

    selected_panels = []
    selected_issues = []
    selected_operations = []
    if selected_group:
        group_id = int(selected_group["id"])
        selected_panels = get_group_panels(group_id)
        selected_issues = _decorate_issues(group_id)
        selected_operations = [
            normalize_operation_row(item)
            for item in get_group_operations(group_id, limit=8)
        ]

    base_query = urlencode({"q": q} if q else {})
    return templates.TemplateResponse(
        "uk.html",
        {
            "request": request,
            "groups": group_page["items"],
            "group_page": group_page,
            "statistics": get_group_statistics(),
            "filters": {"q": q},
            "base_query": base_query,
            "row_query": urlencode(
                {**({"q": q} if q else {}), "page": group_page["page"]}
            ),
            "selected_group": selected_group,
            "selected_panels": selected_panels,
            "selected_issues": selected_issues,
            "selected_operations": selected_operations,
            "is_admin": _is_admin(request),
            "notice": notice,
        },
    )


@router.post("/uk/group")
def uk_group_create(
    request: Request,
    name: str = Form(...),
    legal_name: str = Form(""),
    contact_name: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    legal_address: str = Form(""),
    actual_address: str = Form(""),
    crm_login: str = Form(""),
    crm_password: str = Form(""),
    note: str = Form(""),
):
    try:
        group_id = save_group(
            name=name,
            legal_name=legal_name,
            contact_name=contact_name,
            phone=phone,
            email=email,
            legal_address=legal_address,
            actual_address=actual_address,
            crm_login=crm_login if _is_admin(request) else "",
            crm_password=crm_password if _is_admin(request) else "",
            note=note,
            created_by=_user_name(request),
        )
    except ValueError:
        return _redirect(notice="company_error")
    log_event(
        request=request,
        action="uk_create",
        object_type="Управляющая компания",
        object_name=name,
        details="Карточка УК создана",
        uk_group_id=group_id,
    )
    return _redirect(group_id, notice="company_created")


@router.post("/uk/{group_id}/update")
def uk_group_update(
    request: Request,
    group_id: int,
    name: str = Form(...),
    legal_name: str = Form(""),
    contact_name: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    legal_address: str = Form(""),
    actual_address: str = Form(""),
    crm_login: str = Form(""),
    crm_password: str = Form(""),
    note: str = Form(""),
):
    try:
        update_group(
            group_id,
            name,
            legal_name=legal_name,
            contact_name=contact_name,
            phone=phone,
            email=email,
            legal_address=legal_address,
            actual_address=actual_address,
            crm_login=crm_login,
            crm_password=crm_password or None,
            note=note,
            allow_credentials=_is_admin(request),
        )
    except ValueError:
        return _redirect(group_id, notice="company_error")
    log_event(
        request=request,
        action="uk_update",
        object_type="Управляющая компания",
        object_name=name,
        details=(
            "Карточка и CRM-реквизиты обновлены"
            if _is_admin(request) and (crm_login or crm_password)
            else "Карточка УК обновлена"
        ),
        uk_group_id=group_id,
    )
    return _redirect(group_id, notice="company_updated")


@router.post("/uk/{group_id}/archive")
def uk_group_archive(request: Request, group_id: int):
    if not _is_admin(request):
        return RedirectResponse("/?notice=admin_only", status_code=303)
    group = get_group(group_id)
    if group:
        archive_group(group_id)
        log_event(
            request=request,
            action="uk_archive",
            object_type="Управляющая компания",
            object_name=group["name"],
            details=(
                "УК архивирована. Панели, ключи и история сохранены. "
                "CRM-реквизиты очищены."
            ),
            uk_group_id=group_id,
        )
    return _redirect(notice="company_archived")


@router.post("/uk/{group_id}/credentials/reveal")
def uk_credentials_reveal(request: Request, group_id: int):
    if not _is_admin(request):
        return JSONResponse({"error": "Доступ запрещён"}, status_code=403)
    credentials = get_group_credentials(group_id)
    if not credentials:
        return JSONResponse({"error": "УК не найдена"}, status_code=404)
    return JSONResponse(
        {
            "login": credentials.get("crm_login", ""),
            "password": credentials.get("crm_password", ""),
        },
        headers={"Cache-Control": "no-store"},
    )


@router.get("/uk/{group_id}", response_class=HTMLResponse)
def uk_detail(
    request: Request,
    group_id: int,
    notice: str = Query(""),
):
    group = get_group(group_id)
    if not group:
        return _redirect(notice="company_missing")
    issues = _decorate_issues(group_id, include_closed=True)
    return templates.TemplateResponse(
        "uk_detail.html",
        {
            "request": request,
            "group": group,
            "group_panels": get_group_panels(group_id),
            "available_panels": get_available_panels(group_id),
            "group_issues": issues,
            "available_key_types": get_available_key_types(),
            "operations": [
                normalize_operation_row(item)
                for item in get_group_operations(group_id, limit=40)
            ],
            "is_admin": _is_admin(request),
            "notice": notice,
        },
    )


@router.get("/uk/{group_id}/available-keys")
def uk_available_keys(
    request: Request,
    group_id: int,
    q: str = Query(""),
    key_type_id: int | None = Query(None, ge=1),
    limit: int = Query(60, ge=1, le=100),
):
    if not get_group(group_id):
        return JSONResponse({"error": "УК не найдена"}, status_code=404)
    keys = get_available_keys(q, limit=limit, key_type_id=key_type_id)
    return JSONResponse(
        {
            "items": [
                {
                    "id": item["id"],
                    "number": item["number"],
                    "hex": item["hex_value"],
                    "type_id": item["type_id"],
                    "type": item["type_name"],
                    "color": item["type_color"],
                }
                for item in keys
            ]
        },
        headers={"Cache-Control": "no-store"},
    )


@router.get("/uk/{group_id}/available-panels")
def uk_available_group_panels(
    request: Request,
    group_id: int,
    q: str = Query(""),
    limit: int = Query(60, ge=1, le=100),
):
    if not get_group(group_id):
        return JSONResponse({"error": "УК не найдена"}, status_code=404)
    panels = search_group_panels(group_id, q, limit=limit)
    return JSONResponse(
        {
            "items": [
                {
                    "link_id": item["link_id"],
                    "panel_id": item["panel_id"],
                    "address": item.get("address") or "Адрес не указан",
                    "point": item.get("entrance") or item.get("name") or "Точка доступа",
                    "mac": item.get("mac") or "MAC не указан",
                    "status": item.get("status") or "unknown",
                }
                for item in panels
            ]
        },
        headers={"Cache-Control": "no-store"},
    )


@router.post("/uk/{group_id}/panels/add")
def uk_panel_add(
    request: Request,
    group_id: int,
    panel_id: int = Form(...),
    apartment: str = Form(...),
    comment: str = Form(""),
):
    try:
        link_id = add_panel(
            group_id,
            panel_id,
            apartment,
            comment,
            _user_name(request),
        )
    except ValueError:
        return _redirect(group_id, notice="panel_error")
    panel = get_panel_by_id(panel_id)
    group = get_group(group_id)
    log_event(
        request=request,
        action="uk_panel_add",
        object_type="Панель УК",
        object_name=(panel or {}).get("name") or str(panel_id),
        details=f"Панель закреплена за «{(group or {}).get('name', group_id)}», кв. {apartment}",
        panel_id=panel_id,
        panel_name=(panel or {}).get("name", ""),
        mac=(panel or {}).get("mac", ""),
        address=(panel or {}).get("address", ""),
        apartment=apartment,
        uk_group_id=group_id,
        comment=f"Связь №{link_id}. {comment}".strip(),
    )
    return _redirect(group_id, notice="panel_added")


@router.post("/uk/{group_id}/panels/{link_id}/update")
def uk_panel_update(
    request: Request,
    group_id: int,
    link_id: int,
    apartment: str = Form(...),
    comment: str = Form(""),
):
    try:
        update_panel_link(group_id, link_id, apartment, comment)
    except ValueError:
        return _redirect(group_id, notice="panel_error")
    log_event(
        request=request,
        action="uk_panel_update",
        object_type="Связь УК и панели",
        object_name=str(link_id),
        details=f"Квартира учётной записи изменена: {apartment}",
        apartment=apartment,
        uk_group_id=group_id,
        comment=comment,
    )
    return _redirect(group_id, notice="panel_updated")


@router.post("/uk/{group_id}/panels/{link_id}/detach")
def uk_panel_detach(request: Request, group_id: int, link_id: int):
    try:
        remove_panel(group_id, link_id=link_id)
    except ValueError:
        return _redirect(group_id, notice="panel_has_keys")
    log_event(
        request=request,
        action="uk_panel_detach",
        object_type="Связь УК и панели",
        object_name=str(link_id),
        details="Панель откреплена от УК, история сохранена",
        uk_group_id=group_id,
    )
    return _redirect(group_id, notice="panel_detached")


@router.post("/uk/{group_id}/keys/issue")
def uk_key_issue(
    request: Request,
    group_id: int,
    key_id: int = Form(...),
    panel_link_ids: list[int] = Form(...),
    apartment_override: str = Form(""),
    override_confirmed: int = Form(0),
    comment: str = Form(""),
):
    try:
        result = issue_key(
            group_id=group_id,
            key_id=key_id,
            panel_link_ids=panel_link_ids,
            apartment_override=apartment_override,
            override_confirmed=bool(override_confirmed),
            comment=comment,
            request=request,
            training_mode=bool(request.session.get("training_mode")),
        )
    except ValueError:
        return _redirect(group_id, notice="key_issue_error")
    return _redirect(
        group_id,
        notice=(
            "key_dry_run" if result["status"] == "DRY_RUN"
            else "key_issue_partial" if result["status"] == "PARTIAL"
            else "key_issue_error" if result["status"] == "ERROR"
            else "key_issued"
        ),
    )


@router.post("/uk/{group_id}/keys/{issue_id}/panels/add")
def uk_master_panel_add(
    request: Request,
    group_id: int,
    issue_id: int,
    panel_link_id: int = Form(...),
    apartment_override: str = Form(""),
    override_confirmed: int = Form(0),
):
    try:
        result = add_master_panel(
            group_id=group_id,
            issue_id=issue_id,
            panel_link_id=panel_link_id,
            apartment_override=apartment_override,
            override_confirmed=bool(override_confirmed),
            request=request,
            training_mode=bool(request.session.get("training_mode")),
        )
    except ValueError:
        return _redirect(group_id, notice="master_error")
    return _redirect(
        group_id,
        notice="key_dry_run" if result["status"] == "DRY_RUN" else "master_added",
    )


@router.post("/uk/{group_id}/programming/{programming_id}/retry")
def uk_programming_retry(
    request: Request,
    group_id: int,
    programming_id: int,
):
    try:
        result = retry_programming(
            programming_id,
            request=request,
            training_mode=bool(request.session.get("training_mode")),
        )
    except ValueError:
        return _redirect(group_id, notice="programming_error")
    return _redirect(
        group_id,
        notice="key_dry_run" if result["status"] == "DRY_RUN" else "programming_retried",
    )


@router.post("/uk/{group_id}/programming/{programming_id}/unlink")
def uk_programming_unlink(
    request: Request,
    group_id: int,
    programming_id: int,
):
    try:
        unlink_accounting(programming_id, request=request)
    except ValueError:
        return _redirect(group_id, notice="programming_error")
    return _redirect(group_id, notice="programming_unlinked")


@router.post("/uk/{group_id}/programming/{programming_id}/remove-crm")
def uk_programming_remove_crm(
    request: Request,
    group_id: int,
    programming_id: int,
):
    if not _is_admin(request):
        return RedirectResponse("/?notice=admin_only", status_code=303)
    try:
        result = remove_from_crm(
            programming_id,
            request=request,
            training_mode=bool(request.session.get("training_mode")),
        )
    except ValueError:
        return _redirect(group_id, notice="programming_error")
    return _redirect(
        group_id,
        notice="key_dry_run" if result["status"] == "DRY_RUN" else "crm_removed",
    )
