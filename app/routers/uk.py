from urllib.parse import urlencode

from fastapi import APIRouter, Request, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from app.services import find_key, is_ambiguous_key, write_key_to_panels
from app.services.audit import log_event
from app.templates_config import templates
from app.repositories.panel_repository import get_panel_by_id
from app.repositories.key_repository import get_key_types

from app.repositories.uk_repository import (
    get_group,
    get_group_page,
    get_group_statistics,
    save_group,
    update_group,
    delete_group,
    delete_notification_draft,
    get_group_panels,
    get_available_panels,
    add_panels,
    remove_panel,
    get_group_keys,
    get_notification_drafts,
    save_notification_draft,
    add_keys,
    remove_key,
)

router = APIRouter()


# =========================================================
# СПИСОК УПРАВЛЯЮЩИХ КОМПАНИЙ
# =========================================================

@router.get("/uk", response_class=HTMLResponse)
def uk_page(
    request: Request,
    q: str = Query(""),
    cooperation_state: str = Query(""),
    page: int = Query(1, ge=1),
    selected_group_id: int = Query(0, ge=0),
):
    group_page = get_group_page(
        query=q,
        cooperation_state=cooperation_state,
        page=page,
        page_size=20,
    )
    selected_group = (
        get_group(selected_group_id)
        if selected_group_id
        else None
    )
    if not selected_group and group_page["items"]:
        selected_group = get_group(int(group_page["items"][0]["id"]))

    selected_notifications = (
        get_notification_drafts(int(selected_group["id"]), limit=5)
        if selected_group
        else []
    )
    selected_panels = (
        get_group_panels(int(selected_group["id"]))[:8]
        if selected_group
        else []
    )
    filters = {
        "q": q,
        "cooperation_state": cooperation_state,
    }
    base_params = {
        key: value
        for key, value in filters.items()
        if value not in ("", None)
    }

    return templates.TemplateResponse(
        "uk.html",
        {
            "request": request,
            "groups": group_page["items"],
            "group_page": group_page,
            "statistics": get_group_statistics(),
            "filters": filters,
            "base_query": urlencode(base_params),
            "row_query": urlencode(
                {**base_params, "page": group_page["page"]}
            ),
            "selected_group": selected_group,
            "selected_notifications": selected_notifications,
            "selected_panels": selected_panels,
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
    legal_name: str = Form(""),
    contact_name: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    legal_address: str = Form(""),
    contract_number: str = Form(""),
    cooperation_status: str = Form("potential"),
    account_manager: str = Form(""),
    next_contact_at: str = Form(""),
    cooperation_note: str = Form(""),
):
    group_id = save_group(
        name=name,
        note=note,
        legal_name=legal_name,
        contact_name=contact_name,
        phone=phone,
        email=email,
        legal_address=legal_address,
        contract_number=contract_number,
        created_by=request.session.get("user", {}).get("full_name", ""),
        cooperation_status=cooperation_status,
        account_manager=account_manager,
        next_contact_at=next_contact_at,
        cooperation_note=cooperation_note,
    )

    log_event(
        request=request,
        action="uk_create",
        object_type="Управляющая компания",
        object_name=name,
        details=note or "Карточка УК сохранена",
    )

    return RedirectResponse(
        url=f"/uk?selected_group_id={group_id}",
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
    legal_name: str = Form(""),
    contact_name: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    legal_address: str = Form(""),
    contract_number: str = Form(""),
    cooperation_status: str = Form("potential"),
    account_manager: str = Form(""),
    next_contact_at: str = Form(""),
    cooperation_note: str = Form(""),
    return_to: str = Form("list"),
):
    update_group(
        group_id=group_id,
        name=name,
        note=note,
        legal_name=legal_name,
        contact_name=contact_name,
        phone=phone,
        email=email,
        legal_address=legal_address,
        contract_number=contract_number,
        cooperation_status=cooperation_status,
        account_manager=account_manager,
        next_contact_at=next_contact_at,
        cooperation_note=cooperation_note,
    )

    log_event(
        request=request,
        action="uk_update",
        object_type="Управляющая компания",
        object_name=name,
        details=note or "Карточка УК изменена",
    )

    return RedirectResponse(
        url=(
            f"/uk/{group_id}"
            if return_to == "detail"
            else f"/uk?selected_group_id={group_id}"
        ),
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
            "notification_drafts": get_notification_drafts(group_id),
            "key_types": get_key_types(include_archived=False),
            "message": None,
        },
    )


# =========================================================
# ДОБАВЛЕНИЕ ПАНЕЛЕЙ В УК
# =========================================================

@router.post("/uk/{group_id}/notifications/draft")
def uk_notification_draft(
    request: Request,
    group_id: int,
    title: str = Form(...),
    body: str = Form(...),
    category: str = Form("announcement"),
    channel: str = Form("dtel"),
    audience: str = Form("all"),
    audience_details: str = Form(""),
):
    group = get_group(group_id)
    if not group:
        return RedirectResponse(url="/uk", status_code=303)

    save_notification_draft(
        group_id=group_id,
        title=title,
        body=body,
        category=category,
        channel=channel,
        audience=audience,
        audience_details=audience_details,
        created_by=request.session.get("user", {}).get("full_name", ""),
    )
    log_event(
        request=request,
        action="uk_notification_draft",
        object_type="Черновик уведомления",
        object_name=title,
        details=f"Черновик создан для УК «{group.get('name')}». Отправка не выполнялась.",
        uk_group_id=group_id,
    )
    return RedirectResponse(
        url=f"/uk/{group_id}#notifications",
        status_code=303,
    )


@router.post("/uk/{group_id}/notifications/delete")
def uk_notification_delete(
    request: Request,
    group_id: int,
    draft_id: int = Form(...),
):
    group = get_group(group_id)
    draft = next(
        (
            item
            for item in get_notification_drafts(group_id)
            if int(item["id"]) == draft_id
        ),
        None,
    )
    delete_notification_draft(group_id, draft_id)
    if group and draft:
        log_event(
            request=request,
            action="uk_notification_draft_delete",
            object_type="Черновик уведомления",
            object_name=draft.get("title") or str(draft_id),
            details=f"Черновик удалён из УК «{group.get('name')}»",
            uk_group_id=group_id,
        )
    return RedirectResponse(
        url=f"/uk/{group_id}#notifications",
        status_code=303,
    )


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
            "notification_drafts": get_notification_drafts(group_id),
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
