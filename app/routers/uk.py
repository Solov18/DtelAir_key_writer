from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from app.services import find_key, is_ambiguous_key, write_key_to_panels
from app.services.audit import log_event
from app.templates_config import templates
from app.repositories.panel_repository import get_panel_by_id
from app.repositories.key_repository import get_key_types

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
    request: Request,
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

    log_event(
        request=request,
        action="uk_create",
        object_type="Управляющая компания",
        object_name=name,
        details=note or "Карточка УК сохранена",
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
    request: Request,
    group_id: int = Form(...),
):
    group = get_group(group_id)
    group_keys = get_group_keys(group_id) if group else []
    delete_group(group_id)

    if group:
        for key in group_keys:
            log_event(
                request=request,
                action="key_release",
                object_type="Ключ",
                object_name=f"{key.get('type_name') or 'Без типа'} №{key.get('number')}",
                details=f"Ключ освобождён при удалении УК «{group.get('name')}»",
                printed_number=key.get("number", ""),
                hex_value=key.get("hex_value", "-"),
                key_id=key.get("id"),
                key_type=key.get("type_name", ""),
                uk_group_id=group_id,
            )
        log_event(
            request=request,
            action="uk_delete",
            object_type="Управляющая компания",
            object_name=group.get("name") or str(group_id),
            details="УК и её связи удалены",
        )

    return RedirectResponse(
        url="/uk",
        status_code=303,
    )


# =========================================================
# РЕДАКТИРОВАНИЕ УК
# =========================================================

@router.post("/uk/{group_id}/update")
def uk_update(
    request: Request,
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

    log_event(
        request=request,
        action="uk_update",
        object_type="Управляющая компания",
        object_name=name,
        details=note or "Карточка УК изменена",
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
            "key_types": get_key_types(include_archived=False),
            "message": None,
        },
    )


# =========================================================
# ДОБАВЛЕНИЕ ПАНЕЛЕЙ В УК
# =========================================================

@router.post("/uk/{group_id}/panels/add")
def uk_add_panels(
    request: Request,
    group_id: int,
    panel_ids: list[int] = Form([]),
):
    add_panels(
        group_id=group_id,
        panel_ids=panel_ids,
    )

    group = get_group(group_id)
    log_event(
        request=request,
        action="uk_panels_add",
        object_type="Управляющая компания",
        object_name=(group or {}).get("name") or str(group_id),
        details=f"Добавлено панелей: {len(panel_ids)}",
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
    request: Request,
    group_id: int,
    panel_id: int = Form(...),
):
    group = get_group(group_id)
    panel = get_panel_by_id(panel_id)
    remove_panel(
        group_id=group_id,
        panel_id=panel_id,
    )

    log_event(
        request=request,
        action="uk_panel_remove",
        object_type="Управляющая компания",
        object_name=(group or {}).get("name") or str(group_id),
        details=f"Удалена панель: {(panel or {}).get('name') or panel_id}",
        panel_name=(panel or {}).get("name", ""),
        mac=(panel or {}).get("mac", ""),
        address=(panel or {}).get("address", ""),
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
    key_type_id: int = Form(0),
):
    numbers = [
        value.strip()
        for value in key_values.replace(",", " ").split()
        if value.strip()
    ]

    result = add_keys(
        group_id=group_id,
        key_numbers=numbers,
        key_type_id=key_type_id or None,
    )

    group = get_group(group_id)

    if not group:
        return RedirectResponse(
            url="/uk",
            status_code=303,
        )

    for key in result["added"]:
        log_event(
            request=request,
            action="key_assign_uk",
            object_type="Ключ",
            object_name=f"{key.get('type_name') or 'Без типа'} №{key.get('number')}",
            details=f"Ключ закреплён за УК «{group.get('name')}»",
            printed_number=key.get("number", ""),
            hex_value=key.get("hex_value", "-"),
            key_id=key.get("id"),
            key_type=key.get("type_name", ""),
            uk_group_id=group_id,
        )

    log_event(
        request=request,
        action="uk_keys_add",
        object_type="Управляющая компания",
        object_name=group.get("name") or str(group_id),
        details=(
            f"Добавлено ключей: {len(result['added'])}; "
            f"не найдено: {len(result['not_found'])}; "
            f"нужно выбрать тип: {len(result['ambiguous'])}"
        ),
    )

    return templates.TemplateResponse(
        "uk_detail.html",
        {
            "request": request,
            "group": group,
            "group_panels": get_group_panels(group_id),
            "available_panels": get_available_panels(group_id),
            "group_keys": get_group_keys(group_id),
            "key_types": get_key_types(include_archived=False),
            "message": result,
        },
    )


# =========================================================
# УДАЛЕНИЕ КЛЮЧА ИЗ УК
# =========================================================

@router.post("/uk/{group_id}/keys/remove")
def uk_remove_key(
    request: Request,
    group_id: int,
    key_id: int = Form(...),
):
    group = get_group(group_id)
    key = next(
        (item for item in get_group_keys(group_id) if int(item["id"]) == int(key_id)),
        None,
    )
    remove_key(
        group_id=group_id,
        key_id=key_id,
    )

    log_event(
        request=request,
        action="uk_key_remove",
        object_type="Управляющая компания",
        object_name=(group or {}).get("name") or str(group_id),
        details=f"Удалён ключ: {(key or {}).get('number') or key_id}",
        printed_number=(key or {}).get("number", ""),
        hex_value=(key or {}).get("hex_value", "-"),
        key_id=(key or {}).get("id") or key_id,
        key_type=(key or {}).get("type_name", ""),
        uk_group_id=group_id,
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
    key_type_id: int = Form(0),
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
        item = find_key(value, key_type_id or None)

        if item and not is_ambiguous_key(item):
            results = write_key_to_panels(
                "uk",
                item,
                panels,
                flat_num=flat_num,
                inner=inner,
                address=f"УК: {group['name']}",
                request=request,
                assignment_type="uk",
                uk_group_id=group_id,
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
