from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from app.services import get_panels, find_key, write_key_to_panels
from app.templates_config import templates
from app.repositories.employee_repository import (
    get_active_employees,
    get_employee,
    get_employee_by_name,
    get_employees_count,
    get_employee_keys_count,
    get_employee_keys,
    create_employee,
    soft_delete_employee,
    attach_key_to_employee,
    remove_employee_key,
)

router = APIRouter()


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
    create_employee(full_name=full_name, note=note)
    return RedirectResponse("/employees", status_code=303)


@router.post("/employees/delete")
def employees_delete(employee_id: int = Form(...)):
    soft_delete_employee(employee_id)
    return RedirectResponse("/employees", status_code=303)


@router.get("/employees/{employee_id}", response_class=HTMLResponse)
def employee_detail(request: Request, employee_id: int):
    employee = get_employee(employee_id)

    if not employee:
        return RedirectResponse("/employees", status_code=303)

    return templates.TemplateResponse(
        "employee_detail.html",
        {
            "request": request,
            "employee": employee,
            "employee_keys": get_employee_keys(employee_id),
            "message": None,
        },
    )


@router.post("/employees/{employee_id}/keys/add", response_class=HTMLResponse)
def employee_add_keys(
    request: Request,
    employee_id: int,
    key_values: str = Form(...),
):
    employee = get_employee(employee_id)

    if not employee:
        return RedirectResponse("/employees", status_code=303)

    not_found = []

    for value in [x.strip() for x in key_values.replace(",", " ").split() if x.strip()]:
        key = find_key(value)

        if key:
            attach_key_to_employee(employee_id, key["id"])
        else:
            not_found.append(value)

    return templates.TemplateResponse(
        "employee_detail.html",
        {
            "request": request,
            "employee": employee,
            "employee_keys": get_employee_keys(employee_id),
            "message": {"not_found": not_found},
        },
    )


@router.post("/employees/{employee_id}/keys/remove")
def employee_remove_key(
    employee_id: int,
    key_id: int = Form(...),
):
    remove_employee_key(employee_id, key_id)
    return RedirectResponse(f"/employees/{employee_id}", status_code=303)


@router.post("/employees/write", response_class=HTMLResponse)
def employees_write(
    request: Request,
    employee_name: str = Form(...),
    key_values: str = Form(...),
    scope: str = Form("all"),
    panel_ids: list[int] = Form([]),
    flat_num: str = Form("0"),
    inner: int = Form(0),
):
    employee = get_employee_by_name(employee_name)

    if scope == "selected":
        panels = get_panels(panel_ids=panel_ids)
    elif scope == "employee_tag":
        panels = get_panels(tag="employee")
    else:
        panels = get_panels()

    all_results = []

    for value in [x.strip() for x in key_values.replace(",", " ").split() if x.strip()]:
        item = find_key(value)

        if item:
            if employee:
                attach_key_to_employee(employee["id"], item["id"])

            all_results.append(
                {
                    "key": item,
                    "results": write_key_to_panels(
                        "employee",
                        item,
                        panels,
                        flat_num=flat_num,
                        inner=inner,
                        address=f"Сотрудник: {employee_name}",
                        request=request,
                    ),
                }
            )
        else:
            all_results.append(
                {
                    "key": {
                        "number": value,
                        "hex_value": "НЕ НАЙДЕН",
                    },
                    "results": [],
                }
            )

    return templates.TemplateResponse(
        "write_results.html",
        {
            "request": request,
            "title": f"Результат записи сотрудника: {employee_name}",
            "all_results": all_results,
        },
    )