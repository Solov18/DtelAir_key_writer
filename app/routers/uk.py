from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from app.services import find_key, write_key_to_panels
from app.templates_config import templates

from app.repositories.uk_repository import (
    get_groups,
    get_group,
    save_group,
    update_group,
    delete_group,
    get_group_panels,
    get_available_panels,
    add_panels,
    remove_panel,
    get_group_keys,
    add_keys,
    remove_key,
)

router = APIRouter()


# =========================================================
# СПИСОК УПРАВЛЯЮЩИХ КОМПАНИЙ
# =========================================================

@router.get("/uk", response_class=HTMLResponse)
def uk_page(request: Request):
    groups = get_groups()

    return templates.TemplateResponse(
        "uk.html",
        {
            "request": request,
            "groups": groups,
        },
    )


# =========================================================
# СОЗДАНИЕ УК
# =========================================================

@router.post("/uk/group")
def uk_group(
    name: str = Form(...),
    note: str = Form(""),
    crm_login: str = Form(""),
    crm_password: str = Form(""),
):
    save_group(
        name=name,
        note=note,
        crm_login=crm_login,
        crm_password=crm_password,
    )

    return RedirectResponse(
        url="/uk",
        status_code=303,
    )


# =========================================================
# УДАЛЕНИЕ УК
# ВАЖНО: этот роут находится выше /uk/{group_id}
# =========================================================

@router.post("/uk/delete")
def uk_delete(
    group_id: int = Form(...),
):
    delete_group(group_id)

    return RedirectResponse(
        url="/uk",
        status_code=303,
    )


# =========================================================
# РЕДАКТИРОВАНИЕ УК
# =========================================================

@router.post("/uk/{group_id}/update")
def uk_update(
    group_id: int,
    name: str = Form(...),
    note: str = Form(""),
    crm_login: str = Form(""),
    crm_password: str = Form(""),
):
    update_group(
        group_id=group_id,
        name=name,
        note=note,
        crm_login=crm_login,
        crm_password=crm_password,
    )

    return RedirectResponse(
        url="/uk",
        status_code=303,
    )


# =========================================================
# СТРАНИЦА КОНКРЕТНОЙ УК
# =========================================================

@router.get("/uk/{group_id}", response_class=HTMLResponse)
def uk_detail(
    request: Request,
    group_id: int,
):
    group = get_group(group_id)

    if not group:
        return RedirectResponse(
            url="/uk",
            status_code=303,
        )

    return templates.TemplateResponse(
        "uk_detail.html",
        {
            "request": request,
            "group": group,
            "group_panels": get_group_panels(group_id),
            "available_panels": get_available_panels(group_id),
            "group_keys": get_group_keys(group_id),
            "message": None,
        },
    )


# =========================================================
# ДОБАВЛЕНИЕ ПАНЕЛЕЙ В УК
# =========================================================

@router.post("/uk/{group_id}/panels/add")
def uk_add_panels(
    group_id: int,
    panel_ids: list[int] = Form([]),
):
    add_panels(
        group_id=group_id,
        panel_ids=panel_ids,
    )

    return RedirectResponse(
        url=f"/uk/{group_id}",
        status_code=303,
    )


# =========================================================
# УДАЛЕНИЕ ПАНЕЛИ ИЗ УК
# =========================================================

@router.post("/uk/{group_id}/panels/remove")
def uk_remove_panel(
    group_id: int,
    panel_id: int = Form(...),
):
    remove_panel(
        group_id=group_id,
        panel_id=panel_id,
    )

    return RedirectResponse(
        url=f"/uk/{group_id}",
        status_code=303,
    )


# =========================================================
# ДОБАВЛЕНИЕ КЛЮЧЕЙ В УК
# =========================================================

@router.post(
    "/uk/{group_id}/keys/add",
    response_class=HTMLResponse,
)
def uk_add_keys(
    request: Request,
    group_id: int,
    key_values: str = Form(...),
):
    numbers = [
        value.strip()
        for value in key_values.replace(",", " ").split()
        if value.strip()
    ]

    result = add_keys(
        group_id=group_id,
        key_numbers=numbers,
    )

    group = get_group(group_id)

    if not group:
        return RedirectResponse(
            url="/uk",
            status_code=303,
        )

    return templates.TemplateResponse(
        "uk_detail.html",
        {
            "request": request,
            "group": group,
            "group_panels": get_group_panels(group_id),
            "available_panels": get_available_panels(group_id),
            "group_keys": get_group_keys(group_id),
            "message": result,
        },
    )


# =========================================================
# УДАЛЕНИЕ КЛЮЧА ИЗ УК
# =========================================================

@router.post("/uk/{group_id}/keys/remove")
def uk_remove_key(
    group_id: int,
    key_id: int = Form(...),
):
    remove_key(
        group_id=group_id,
        key_id=key_id,
    )

    return RedirectResponse(
        url=f"/uk/{group_id}",
        status_code=303,
    )


# =========================================================
# ЗАПИСЬ КЛЮЧЕЙ НА ПАНЕЛИ УК
# =========================================================

@router.post(
    "/uk/{group_id}/write",
    response_class=HTMLResponse,
)
def uk_write(
    request: Request,
    group_id: int,
    key_values: str = Form(...),
    flat_num: str = Form("0"),
    inner: int = Form(0),
):
    group = get_group(group_id)

    if not group:
        return RedirectResponse(
            url="/uk",
            status_code=303,
        )

    panels = get_group_panels(group_id)

    all_results = []

    numbers = [
        value.strip()
        for value in key_values.replace(",", " ").split()
        if value.strip()
    ]

    for value in numbers:
        item = find_key(value)

        if item:
            results = write_key_to_panels(
                "uk",
                item,
                panels,
                flat_num=flat_num,
                inner=inner,
                address=f"УК: {group['name']}",
            )

            all_results.append(
                {
                    "key": item,
                    "results": results,
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
            "title": f"Результат записи УК: {group['name']}",
            "all_results": all_results,
        },
    )