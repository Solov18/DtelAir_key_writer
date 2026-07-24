from urllib.parse import urlencode

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.repositories.employee_repository import (
    close_employee_key,
    create_employee,
    dismiss_employee,
    get_active_employees,
    get_dismissed_employees,
    get_dismissed_employees_count,
    get_employee,
    get_employee_active_key,
    get_employee_active_keys,
    get_employee_any_status,
    get_employee_by_name,
    get_employee_filter_options,
    get_employee_key_history,
    get_employee_page,
    get_employee_statistics,
    get_employee_keys_count,
    get_employees_count,
    issue_key_to_employee,
    restore_employee,
    update_employee,
    update_employee_key_comment,
    update_employee_key_history,
)
from app.repositories.key_repository import get_key_types
from app.services import find_key, get_panels, is_ambiguous_key, write_key_to_panels
from app.services.audit import log_event
from app.templates_config import templates


router = APIRouter()


KEY_STATUS_LABELS = {
    "active": "Действующий",
    "replaced": "Заменён",
    "lost": "Утерян",
    "damaged": "Повреждён",
    "dismissed": "Сотрудник уволен",
    "inactive": "Деактивирован",
}


def _employee_detail_context(
    request: Request,
    employee_id: int,
    message: dict | None = None,
) -> dict:
    employee = get_employee_any_status(employee_id)

    active_keys = get_employee_active_keys(employee_id)
    return {
        "request": request,
        "employee": employee,
        "is_dismissed": bool(employee and not employee["enabled"]),
        "active_key": active_keys[0] if active_keys else None,
        "active_keys": active_keys,
        "key_history": get_employee_key_history(employee_id),
        "status_labels": KEY_STATUS_LABELS,
        "key_types": get_key_types(include_archived=False),
        "message": message,
    }


def _employee_assignment_context(
    employee_id: int,
    assignment_id: int,
) -> dict | None:
    for active_key in get_employee_active_keys(employee_id):
        if int(active_key["assignment_id"]) == int(assignment_id):
            return active_key

    return next(
        (
            item
            for item in get_employee_key_history(employee_id)
            if int(item["assignment_id"]) == int(assignment_id)
        ),
        None,
    )


def _key_log_fields(key: dict | None) -> dict:
    key = key or {}
    return {
        "key_id": key.get("key_id") or key.get("id"),
        "key_type": key.get("type_name") or key.get("key_type", ""),
        "printed_number": key.get("number", ""),
        "hex_value": key.get("hex_value", "-"),
    }


def _employee_list_context(
    request: Request,
    *,
    enabled: bool,
    query: str,
    key_status: str,
    department: str,
    position: str,
    page: int,
    selected_employee_id: int,
) -> dict:
    employee_page = get_employee_page(
        enabled=enabled,
        query=query,
        key_status=key_status,
        department=department,
        position=position,
        page=page,
        page_size=20,
    )
    selected_employee = (
        get_employee_any_status(selected_employee_id)
        if selected_employee_id
        else None
    )
    if selected_employee and bool(selected_employee["enabled"]) != enabled:
        selected_employee = None
    if not selected_employee and employee_page["items"]:
        selected_employee = get_employee_any_status(
            int(employee_page["items"][0]["id"])
        )
    selected_keys = (
        get_employee_active_keys(int(selected_employee["id"]))
        if selected_employee
        else []
    )

    filters = {
        "q": query,
        "key_status": key_status,
        "department": department,
        "position": position,
    }
    base_params = {
        key: value
        for key, value in filters.items()
        if value not in ("", None)
    }
    if not enabled:
        base_params["view"] = "dismissed"

    return {
        "request": request,
        "employees": employee_page["items"],
        "employee_page": employee_page,
        "statistics": get_employee_statistics(),
        "filter_options": get_employee_filter_options(),
        "filters": filters,
        "base_query": urlencode(base_params),
        "row_query": urlencode({**base_params, "page": employee_page["page"]}),
        "selected_employee": selected_employee,
        "selected_keys": selected_keys,
        "current_view": "active" if enabled else "dismissed",
        "key_types": get_key_types(include_archived=False),
    }


@router.get("/employees", response_class=HTMLResponse)
def employees_page(
    request: Request,
    q: str = Query(""),
    key_status: str = Query(""),
    department: str = Query(""),
    position: str = Query(""),
    page: int = Query(1, ge=1),
    selected_employee_id: int = Query(0, ge=0),
):
    return templates.TemplateResponse(
        "employees.html",
        _employee_list_context(
            request,
            enabled=True,
            query=q,
            key_status=key_status,
            department=department,
            position=position,
            page=page,
            selected_employee_id=selected_employee_id,
        ),
    )


@router.get("/employees/dismissed", response_class=HTMLResponse)
def dismissed_employees_page(
    request: Request,
    q: str = Query(""),
    department: str = Query(""),
    position: str = Query(""),
    page: int = Query(1, ge=1),
    selected_employee_id: int = Query(0, ge=0),
):
    return templates.TemplateResponse(
        "employees.html",
        _employee_list_context(
            request,
            enabled=False,
            query=q,
            key_status="",
            department=department,
            position=position,
            page=page,
            selected_employee_id=selected_employee_id,
        ),
    )


@router.post("/employees/add")
def employees_add(
    request: Request,
    full_name: str = Form(...),
    note: str = Form(""),
    position: str = Form(""),
    department: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
):
    employee_id = create_employee(
        full_name=full_name,
        note=note,
        position=position,
        department=department,
        phone=phone,
        email=email,
        created_by=request.session.get("user", {}).get("full_name", ""),
    )
    log_event(
        request=request,
        action="employee_create",
        object_type="Сотрудник",
        object_name=full_name,
        details=note or "Карточка сотрудника создана",
    )
    return RedirectResponse(
        f"/employees?selected_employee_id={employee_id}",
        status_code=303,
    )


@router.post("/employees/{employee_id}/edit")
def employee_edit(
    request: Request,
    employee_id: int,
    full_name: str = Form(...),
    note: str = Form(""),
    position: str = Form(""),
    department: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    return_to: str = Form("detail"),
):
    update_employee(
        employee_id=employee_id,
        full_name=full_name,
        note=note,
        position=position,
        department=department,
        phone=phone,
        email=email,
    )
    log_event(
        request=request,
        action="employee_update",
        object_type="Сотрудник",
        object_name=full_name,
        details=note or "Карточка сотрудника изменена",
    )
    redirect_url = (
        f"/employees?selected_employee_id={employee_id}"
        if return_to == "list"
        else f"/employees/{employee_id}"
    )
    return RedirectResponse(redirect_url, status_code=303)


@router.post("/employees/{employee_id}/dismiss")
def employee_dismiss(
    request: Request,
    employee_id: int,
    comment: str = Form(""),
):
    employee = get_employee_any_status(employee_id)
    active_keys = get_employee_active_keys(employee_id)
    dismiss_employee(employee_id=employee_id, comment=comment)
    log_event(
        request=request,
        action="employee_dismiss",
        object_type="Сотрудник",
        object_name=(employee or {}).get("full_name") or str(employee_id),
        details=comment or "Сотрудник уволен",
    )
    for active_key in active_keys:
        log_event(
            request=request,
            action="employee_key_close",
            object_type="Ключ",
            object_name=active_key.get("number") or str(active_key["key_id"]),
            details="Ключ освобождён при увольнении сотрудника",
            employee_id=employee_id,
            comment=comment,
            **_key_log_fields(active_key),
        )
    return RedirectResponse("/employees/dismissed", status_code=303)


@router.post("/employees/{employee_id}/restore")
def employee_restore(request: Request, employee_id: int):
    employee = get_employee_any_status(employee_id)
    restore_employee(employee_id)
    log_event(
        request=request,
        action="employee_restore",
        object_type="Сотрудник",
        object_name=(employee or {}).get("full_name") or str(employee_id),
        details="Сотрудник восстановлен",
    )
    return RedirectResponse(f"/employees/{employee_id}", status_code=303)


@router.post("/employees/delete")
def employees_delete(request: Request, employee_id: int = Form(...)):
    employee = get_employee_any_status(employee_id)
    active_keys = get_employee_active_keys(employee_id)
    dismiss_employee(
        employee_id=employee_id,
        comment="Сотрудник уволен",
    )
    log_event(
        request=request,
        action="employee_dismiss",
        object_type="Сотрудник",
        object_name=(employee or {}).get("full_name") or str(employee_id),
        details="Сотрудник уволен",
    )
    for active_key in active_keys:
        log_event(
            request=request,
            action="employee_key_close",
            object_type="Ключ",
            object_name=active_key.get("number") or str(active_key["key_id"]),
            details="Ключ освобождён при увольнении сотрудника",
            employee_id=employee_id,
            **_key_log_fields(active_key),
        )
    return RedirectResponse("/employees/dismissed", status_code=303)


@router.get("/employees/{employee_id}", response_class=HTMLResponse)
def employee_detail(request: Request, employee_id: int):
    employee = get_employee_any_status(employee_id)

    if not employee:
        return RedirectResponse("/employees", status_code=303)

    return templates.TemplateResponse(
        "employee_detail.html",
        _employee_detail_context(request, employee_id),
    )


@router.post("/employees/{employee_id}/keys/issue", response_class=HTMLResponse)
def employee_issue_key(
    request: Request,
    employee_id: int,
    key_value: str = Form(...),
    key_type_id: int = Form(0),
    new_key_comment: str = Form(""),
    old_key_status: str = Form("replaced"),
    old_key_reason: str = Form("Выдан новый ключ"),
    old_key_comment: str = Form(""),
):
    employee = get_employee(employee_id)

    if not employee:
        return RedirectResponse("/employees/dismissed", status_code=303)

    key = find_key(key_value.strip(), key_type_id or None)

    if not key or is_ambiguous_key(key):
        return templates.TemplateResponse(
            "employee_detail.html",
            _employee_detail_context(
                request,
                employee_id,
                {
                    "type": "error",
                    "text": f"Ключ «{key_value.strip()}» не найден в базе.",
                },
            ),
        )

    try:
        issue_key_to_employee(
            employee_id=employee_id,
            key_id=key["id"],
            new_key_comment=new_key_comment,
            old_key_status=old_key_status,
            old_key_reason=old_key_reason,
            old_key_comment=old_key_comment,
        )
    except ValueError as error:
        return templates.TemplateResponse(
            "employee_detail.html",
            _employee_detail_context(
                request,
                employee_id,
                {"type": "error", "text": str(error)},
            ),
        )

    log_event(
        request=request,
        action="employee_key_issue",
        object_type="Сотрудник",
        object_name=employee.get("full_name") or str(employee_id),
        details=f"Выдан ключ {key.get('number') or key.get('hex_value')}",
        printed_number=key.get("number", ""),
        hex_value=key.get("hex_value", "-"),
        key_id=key.get("id"),
        key_type=key.get("type_name") or key.get("key_type", ""),
        employee_id=employee_id,
    )

    return RedirectResponse(f"/employees/{employee_id}", status_code=303)


@router.post("/employees/{employee_id}/keys/add", response_class=HTMLResponse)
def employee_add_keys(
    request: Request,
    employee_id: int,
    key_values: str = Form(...),
    key_type_id: int = Form(0),
):
    values = [
        value.strip()
        for value in key_values.replace(",", " ").split()
        if value.strip()
    ]

    if not values:
        return templates.TemplateResponse(
            "employee_detail.html",
            _employee_detail_context(
                request,
                employee_id,
                {"type": "error", "text": "Не указан номер ключа."},
            ),
        )

    keys: list[dict] = []
    for value in dict.fromkeys(values):
        key = find_key(value, key_type_id or None)
        if not key or is_ambiguous_key(key):
            return templates.TemplateResponse(
                "employee_detail.html",
                _employee_detail_context(
                    request,
                    employee_id,
                    {"type": "error", "text": f"Ключ «{value}» не найден."},
                ),
            )
        keys.append(key)

    try:
        for key in keys:
            issue_key_to_employee(
                employee_id=employee_id,
                key_id=key["id"],
            )
    except ValueError as error:
        return templates.TemplateResponse(
            "employee_detail.html",
            _employee_detail_context(
                request,
                employee_id,
                {"type": "error", "text": str(error)},
            ),
        )

    employee = get_employee_any_status(employee_id)
    for key in keys:
        log_event(
            request=request,
            action="employee_key_issue",
            object_type="Сотрудник",
            object_name=(employee or {}).get("full_name") or str(employee_id),
            details=f"Выдан ключ {key.get('number') or key.get('hex_value')}",
            printed_number=key.get("number", ""),
            hex_value=key.get("hex_value", "-"),
            key_id=key.get("id"),
            key_type=key.get("type_name") or key.get("key_type", ""),
            employee_id=employee_id,
        )

    return RedirectResponse(f"/employees/{employee_id}", status_code=303)


@router.post("/employees/{employee_id}/keys/close")
def employee_close_key(
    request: Request,
    employee_id: int,
    assignment_id: int = Form(...),
    status: str = Form(...),
    close_reason: str = Form(...),
    comment: str = Form(""),
):
    employee = get_employee_any_status(employee_id)
    assignment = _employee_assignment_context(employee_id, assignment_id)
    close_employee_key(
        employee_id=employee_id,
        assignment_id=assignment_id,
        status=status,
        close_reason=close_reason,
        comment=comment,
    )
    log_event(
        request=request,
        action="employee_key_close",
        object_type="Сотрудник",
        object_name=(employee or {}).get("full_name") or str(employee_id),
        details=f"{KEY_STATUS_LABELS.get(status, status)}: {close_reason}",
        employee_id=employee_id,
        comment=comment,
        **_key_log_fields(assignment),
    )
    return RedirectResponse(f"/employees/{employee_id}", status_code=303)


@router.post("/employees/{employee_id}/keys/comment")
def employee_key_comment(
    request: Request,
    employee_id: int,
    assignment_id: int = Form(...),
    comment: str = Form(""),
):
    employee = get_employee_any_status(employee_id)
    assignment = _employee_assignment_context(employee_id, assignment_id)
    update_employee_key_comment(
        employee_id=employee_id,
        assignment_id=assignment_id,
        comment=comment,
    )
    log_event(
        request=request,
        action="employee_key_comment",
        object_type="Сотрудник",
        object_name=(employee or {}).get("full_name") or str(employee_id),
        details=comment or "Комментарий очищен",
        employee_id=employee_id,
        comment=comment,
        **_key_log_fields(assignment),
    )
    return RedirectResponse(f"/employees/{employee_id}", status_code=303)


@router.post("/employees/{employee_id}/keys/history/edit")
def employee_key_history_edit(
    request: Request,
    employee_id: int,
    assignment_id: int = Form(...),
    status: str = Form(...),
    close_reason: str = Form(...),
    comment: str = Form(""),
):
    employee = get_employee_any_status(employee_id)
    assignment = _employee_assignment_context(employee_id, assignment_id)
    update_employee_key_history(
        employee_id=employee_id,
        assignment_id=assignment_id,
        status=status,
        close_reason=close_reason,
        comment=comment,
    )
    log_event(
        request=request,
        action="employee_key_history_update",
        object_type="Сотрудник",
        object_name=(employee or {}).get("full_name") or str(employee_id),
        details=f"{KEY_STATUS_LABELS.get(status, status)}: {close_reason}",
        employee_id=employee_id,
        comment=comment,
        **_key_log_fields(assignment),
    )
    return RedirectResponse(f"/employees/{employee_id}", status_code=303)


@router.post("/employees/{employee_id}/keys/remove")
def employee_remove_key(
    request: Request,
    employee_id: int,
    key_id: int = Form(...),
):
    employee = get_employee_any_status(employee_id)
    active_key = next(
        (
            item
            for item in get_employee_active_keys(employee_id)
            if int(item["key_id"]) == int(key_id)
        ),
        None,
    )

    if active_key and active_key["key_id"] == key_id:
        close_employee_key(
            employee_id=employee_id,
            assignment_id=active_key["assignment_id"],
            status="inactive",
            close_reason="Ключ деактивирован вручную",
        )

        log_event(
            request=request,
            action="employee_key_remove",
            object_type="Сотрудник",
            object_name=(employee or {}).get("full_name") or str(employee_id),
            details=f"Деактивирован ключ {active_key.get('number') or key_id}",
            employee_id=employee_id,
            **_key_log_fields(active_key),
        )

    return RedirectResponse(f"/employees/{employee_id}", status_code=303)


@router.post("/employees/write", response_class=HTMLResponse)
def employees_write(
    request: Request,
    employee_name: str = Form(...),
    key_value: str = Form(...),
    key_type_id: int = Form(0),
    scope: str = Form("all"),
    panel_ids: list[int] = Form([]),
    flat_num: str = Form("0"),
    inner: int = Form(0),
    new_key_comment: str = Form(""),
    old_key_status: str = Form("replaced"),
    old_key_reason: str = Form("Выдан новый ключ"),
):
    employee = get_employee_by_name(employee_name)

    if not employee:
        return templates.TemplateResponse(
            "write_results.html",
            {
                "request": request,
                "title": "Ошибка записи ключа",
                "all_results": [
                    {
                        "key": {
                            "number": key_value,
                            "hex_value": "СОТРУДНИК НЕ НАЙДЕН",
                        },
                        "results": [],
                    }
                ],
            },
        )

    item = find_key(key_value.strip(), key_type_id or None)

    if not item or is_ambiguous_key(item):
        return templates.TemplateResponse(
            "write_results.html",
            {
                "request": request,
                "title": f"Результат записи сотрудника: {employee_name}",
                "all_results": [
                    {
                        "key": {
                            "number": key_value,
                            "hex_value": "КЛЮЧ НЕ НАЙДЕН",
                        },
                        "results": [],
                    }
                ],
            },
        )

    try:
        issue_key_to_employee(
            employee_id=employee["id"],
            key_id=item["id"],
            new_key_comment=new_key_comment,
            old_key_status=old_key_status,
            old_key_reason=old_key_reason,
        )
    except ValueError as error:
        return templates.TemplateResponse(
            "write_results.html",
            {
                "request": request,
                "title": "Ошибка выдачи ключа",
                "all_results": [
                    {
                        "key": {
                            "number": key_value,
                            "hex_value": str(error),
                        },
                        "results": [],
                    }
                ],
            },
        )

    panels = get_panels(panel_ids=panel_ids) if scope == "selected" else get_panels()

    results = write_key_to_panels(
        "employee",
        item,
        panels,
        flat_num=flat_num,
        inner=inner,
        address=f"Сотрудник: {employee_name}",
        request=request,
        assignment_type="employee",
        employee_id=employee["id"],
    )

    return templates.TemplateResponse(
        "write_results.html",
        {
            "request": request,
            "title": f"Результат записи сотрудника: {employee_name}",
            "all_results": [{"key": item, "results": results}],
        },
    )
