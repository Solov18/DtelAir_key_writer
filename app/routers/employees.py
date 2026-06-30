from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from app.services import get_panels, find_key, write_key_to_panels
from app.templates_config import templates
from app.repositories.employee_repository import (
    get_active_employees,
    create_employee,
    soft_delete_employee,
)

router = APIRouter()


@router.get("/employees", response_class=HTMLResponse)
def employees_page(request: Request):
    panels = get_panels()
    employees = get_active_employees()

    return templates.TemplateResponse(
        "employees.html",
        {
            "request": request,
            "panels": panels,
            "employees": employees,
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

    return RedirectResponse("/employees", status_code=303)


@router.post("/employees/delete")
def employees_delete(employee_id: int = Form(...)):
    soft_delete_employee(employee_id)

    return RedirectResponse("/employees", status_code=303)


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
    if scope == "selected":
        panels = get_panels(panel_ids=panel_ids)
    elif scope == "employee_tag":
        panels = get_panels(tag="employee")
    else:
        panels = get_panels()

    all_results = []

    for value in [
        x.strip()
        for x in key_values.replace(",", " ").split()
        if x.strip()
    ]:
        item = find_key(value)

        if item:
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