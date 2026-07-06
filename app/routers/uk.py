from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse


from app.services import find_key, write_key_to_panels
from app.templates_config import templates
from app.repositories.uk_repository import (
    get_groups,
    get_group,
    save_group,
    get_group_panels,
    get_available_panels,
    add_panels,
    remove_panel,
    get_group_keys,
    add_keys,
    remove_key,
    delete_group,
    update_group_credentials
)

router = APIRouter()


@router.get("/uk", response_class=HTMLResponse)
def uk_page(request: Request):
    return templates.TemplateResponse(
        "uk.html",
        {
            "request": request,
            "groups": get_groups(),
        },
    )


@router.post("/uk/group")
def uk_group(
    name: str = Form(...),
    note: str = Form(""),
):
    save_group(name=name, note=note)
    return RedirectResponse("/uk", status_code=303)


@router.get("/uk/{group_id}", response_class=HTMLResponse)
def uk_detail(request: Request, group_id: int):
    group = get_group(group_id)

    if not group:
        return RedirectResponse("/uk", status_code=303)

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


@router.post("/uk/{group_id}/panels/add")
def uk_add_panels(
    group_id: int,
    panel_ids: list[int] = Form([]),
):
    add_panels(group_id, panel_ids)
    return RedirectResponse(f"/uk/{group_id}", status_code=303)


@router.post("/uk/{group_id}/panels/remove")
def uk_remove_panel(
    group_id: int,
    panel_id: int = Form(...),
):
    remove_panel(group_id, panel_id)
    return RedirectResponse(f"/uk/{group_id}", status_code=303)


@router.post("/uk/{group_id}/keys/add")
def uk_add_keys(
    request: Request,
    group_id: int,
    key_values: str = Form(...),
):
    numbers = [
        x.strip()
        for x in key_values.replace(",", " ").split()
        if x.strip()
    ]

    result = add_keys(group_id, numbers)

    group = get_group(group_id)

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


@router.post("/uk/{group_id}/keys/remove")
def uk_remove_key(
    group_id: int,
    key_id: int = Form(...),
):
    remove_key(group_id, key_id)
    return RedirectResponse(f"/uk/{group_id}", status_code=303)


@router.post("/uk/{group_id}/write", response_class=HTMLResponse)
def uk_write(
    request: Request,
    group_id: int,
    key_values: str = Form(...),
    flat_num: str = Form("0"),
    inner: int = Form(0),
):
    panels = get_group_panels(group_id)

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
                        "uk",
                        item,
                        panels,
                        flat_num=flat_num,
                        inner=inner,
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
            "title": "Результат записи УК",
            "all_results": all_results,
        },
    )


@router.post("/uk/delete")
def uk_delete(group_id: int = Form(...)):
    delete_group(group_id)
    return RedirectResponse("/uk", status_code=303)

@router.post("/uk/{group_id}/update")
def uk_update(
    group_id: int,
    note: str = Form(""),
    crm_login: str = Form(""),
    crm_password: str = Form(""),
):
    update_group_credentials(
        group_id=group_id,
        note=note,
        crm_login=crm_login,
        crm_password=crm_password,
    )

    return RedirectResponse(f"/uk/{group_id}", status_code=303)