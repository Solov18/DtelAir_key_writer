from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.repositories.employee_repository import (
    close_employee_key,
    create_employee,
    dismiss_employee,
    get_active_employees,
    get_employee,
    get_employee_active_key,
    get_employee_by_name,
    get_employee_key_history,
    get_employee_keys_count,
    get_employees_count,
    issue_key_to_employee,
    update_employee,
    update_employee_key_comment,
    update_employee_key_history,
)
from app.services import find_key, get_panels, write_key_to_panels
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
    """
    Собирает данные для карточки сотрудника.
    """
    employee = get_employee(employee_id)

    return {
        "request": request,
        "employee": employee,
        "active_key": get_employee_active_key(employee_id),
        "key_history": get_employee_key_history(employee_id),
        "status_labels": KEY_STATUS_LABELS,
        "message": message,
    }


@router.get("/employees", response_class=HTMLResponse)
def employees_page(request: Request):
    return templates.TemplateResponse(
        "employees.html",
        {
            "request": request,
            "panels": get_panels(),
            "employees": get_active_employees(),
            "employees_count": get_employees_count(),
            "employee_keys_count": get_employee_keys_count(),
        },
    )


@router.post("/employees/add")
def employees_add(
    full_name: str = Form(...),
    note: str = Form(""),
):
    create_employee(
        full_name=full_name,
        note=note,
    )

    return RedirectResponse(
        "/employees",
        status_code=303,
    )


@router.post("/employees/{employee_id}/edit")
def employee_edit(
    employee_id: int,
    full_name: str = Form(...),
    note: str = Form(""),
):
    update_employee(
        employee_id=employee_id,
        full_name=full_name,
        note=note,
    )

    return RedirectResponse(
        f"/employees/{employee_id}",
        status_code=303,
    )


@router.post("/employees/{employee_id}/dismiss")
def employee_dismiss(
    employee_id: int,
    comment: str = Form(""),
):
    dismiss_employee(
        employee_id=employee_id,
        comment=comment,
    )

    return RedirectResponse(
        "/employees",
        status_code=303,
    )


@router.post("/employees/delete")
def employees_delete(
    employee_id: int = Form(...),
):
    """
    Оставлено для совместимости со старым HTML.

    Сотрудник больше не удаляется.
    Он переводится в статус уволенного.
    """
    dismiss_employee(
        employee_id=employee_id,
        comment="Сотрудник уволен",
    )

    return RedirectResponse(
        "/employees",
        status_code=303,
    )


@router.get(
    "/employees/{employee_id}",
    response_class=HTMLResponse,
)
def employee_detail(
    request: Request,
    employee_id: int,
):
    employee = get_employee(employee_id)

    if not employee:
        return RedirectResponse(
            "/employees",
            status_code=303,
        )

    return templates.TemplateResponse(
        "employee_detail.html",
        _employee_detail_context(
            request=request,
            employee_id=employee_id,
        ),
    )


@router.post(
    "/employees/{employee_id}/keys/issue",
    response_class=HTMLResponse,
)
def employee_issue_key(
    request: Request,
    employee_id: int,
    key_value: str = Form(...),
    new_key_comment: str = Form(""),
    old_key_status: str = Form("replaced"),
    old_key_reason: str = Form("Выдан новый ключ"),
    old_key_comment: str = Form(""),
):
    employee = get_employee(employee_id)

    if not employee:
        return RedirectResponse(
            "/employees",
            status_code=303,
        )

    key = find_key(key_value.strip())

    if not key:
        return templates.TemplateResponse(
            "employee_detail.html",
            _employee_detail_context(
                request=request,
                employee_id=employee_id,
                message={
                    "type": "error",
                    "text": (
                        f"Ключ «{key_value.strip()}» "
                        "не найден в базе."
                    ),
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
                request=request,
                employee_id=employee_id,
                message={
                    "type": "error",
                    "text": str(error),
                },
            ),
        )

    return RedirectResponse(
        f"/employees/{employee_id}",
        status_code=303,
    )


@router.post(
    "/employees/{employee_id}/keys/add",
    response_class=HTMLResponse,
)
def employee_add_keys(
    request: Request,
    employee_id: int,
    key_values: str = Form(...),
):
    """
    Совместимость со старой формой.

    Берётся только один номер ключа.
    Несколько действующих ключей больше не создаются.
    """
    values = [
        value.strip()
        for value in key_values.replace(",", " ").split()
        if value.strip()
    ]

    if not values:
        return templates.TemplateResponse(
            "employee_detail.html",
            _employee_detail_context(
                request=request,
                employee_id=employee_id,
                message={
                    "type": "error",
                    "text": "Не указан номер ключа.",
                },
            ),
        )

    if len(values) > 1:
        return templates.TemplateResponse(
            "employee_detail.html",
            _employee_detail_context(
                request=request,
                employee_id=employee_id,
                message={
                    "type": "error",
                    "text": (
                        "У сотрудника может быть только один "
                        "действующий ключ. Укажите один номер."
                    ),
                },
            ),
        )

    key = find_key(values[0])

    if not key:
        return templates.TemplateResponse(
            "employee_detail.html",
            _employee_detail_context(
                request=request,
                employee_id=employee_id,
                message={
                    "type": "error",
                    "text": f"Ключ «{values[0]}» не найден.",
                },
            ),
        )

    try:
        issue_key_to_employee(
            employee_id=employee_id,
            key_id=key["id"],
            old_key_status="replaced",
            old_key_reason="Выдан новый ключ",
        )
    except ValueError as error:
        return templates.TemplateResponse(
            "employee_detail.html",
            _employee_detail_context(
                request=request,
                employee_id=employee_id,
                message={
                    "type": "error",
                    "text": str(error),
                },
            ),
        )

    return RedirectResponse(
        f"/employees/{employee_id}",
        status_code=303,
    )


@router.post(
    "/employees/{employee_id}/keys/close",
)
def employee_close_key(
    employee_id: int,
    assignment_id: int = Form(...),
    status: str = Form(...),
    close_reason: str = Form(...),
    comment: str = Form(""),
):
    close_employee_key(
        employee_id=employee_id,
        assignment_id=assignment_id,
        status=status,
        close_reason=close_reason,
        comment=comment,
    )

    return RedirectResponse(
        f"/employees/{employee_id}",
        status_code=303,
    )


@router.post(
    "/employees/{employee_id}/keys/comment",
)
def employee_key_comment(
    employee_id: int,
    assignment_id: int = Form(...),
    comment: str = Form(""),
):
    update_employee_key_comment(
        employee_id=employee_id,
        assignment_id=assignment_id,
        comment=comment,
    )

    return RedirectResponse(
        f"/employees/{employee_id}",
        status_code=303,
    )


@router.post(
    "/employees/{employee_id}/keys/history/edit",
)
def employee_key_history_edit(
    employee_id: int,
    assignment_id: int = Form(...),
    status: str = Form(...),
    close_reason: str = Form(...),
    comment: str = Form(""),
):
    update_employee_key_history(
        employee_id=employee_id,
        assignment_id=assignment_id,
        status=status,
        close_reason=close_reason,
        comment=comment,
    )

    return RedirectResponse(
        f"/employees/{employee_id}",
        status_code=303,
    )


@router.post(
    "/employees/{employee_id}/keys/remove",
)
def employee_remove_key(
    employee_id: int,
    key_id: int = Form(...),
):
    """
    Старый маршрут оставлен временно.

    Ключ не удаляется, а переносится в историю.
    """
    active_key = get_employee_active_key(employee_id)

    if active_key and active_key["key_id"] == key_id:
        close_employee_key(
            employee_id=employee_id,
            assignment_id=active_key["assignment_id"],
            status="inactive",
            close_reason="Ключ деактивирован вручную",
        )

    return RedirectResponse(
        f"/employees/{employee_id}",
        status_code=303,
    )


@router.post(
    "/employees/write",
    response_class=HTMLResponse,
)
def employees_write(
    request: Request,
    employee_name: str = Form(...),
    key_value: str = Form(...),
    scope: str = Form("all"),
    panel_ids: list[int] = Form([]),
    flat_num: str = Form("0"),
    inner: int = Form(0),
    new_key_comment: str = Form(""),
    old_key_status: str = Form("replaced"),
    old_key_reason: str = Form("Выдан новый ключ"),
):
    """
    Выдаёт сотруднику один действующий ключ
    и записывает его на выбранные панели.
    """
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

    item = find_key(key_value.strip())

    if not item:
        return templates.TemplateResponse(
            "write_results.html",
            {
                "request": request,
                "title": (
                    f"Результат записи сотрудника: "
                    f"{employee_name}"
                ),
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

    if scope == "selected":
        panels = get_panels(
            panel_ids=panel_ids,
        )
    else:
        panels = get_panels()

    results = write_key_to_panels(
        "employee",
        item,
        panels,
        flat_num=flat_num,
        inner=inner,
        address=f"Сотрудник: {employee_name}",
        request=request,
    )

    return templates.TemplateResponse(
        "write_results.html",
        {
            "request": request,
            "title": (
                f"Результат записи сотрудника: "
                f"{employee_name}"
            ),
            "all_results": [
                {
                    "key": item,
                    "results": results,
                }
            ],
        },
    )