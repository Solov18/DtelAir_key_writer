from uuid import uuid4

from app.repositories import uk_repository
from app.services.audit import log_event
from app.services.crm import (
    crm_add_key_for_company,
    crm_remove_key_for_company,
)


def _actor(request) -> str:
    user = request.session.get("user", {}) if request else {}
    return user.get("full_name") or user.get("login") or "Система"


def _safe_response(value: str, credentials: dict | None = None) -> str:
    text = (value or "").strip()
    for secret in (
        (credentials or {}).get("crm_login", ""),
        (credentials or {}).get("crm_password", ""),
    ):
        if secret:
            text = text.replace(secret, "[СКРЫТО]")
    return text[:1000] or "CRM не вернула пояснение"


def _result_status(result: dict) -> str:
    if result.get("status") == "DRY_RUN":
        return "dry_run"
    return "success" if result.get("ok") else "error"


def _run_programming(
    programming_id: int,
    *,
    operation: str,
    request=None,
) -> dict:
    programming = uk_repository.get_programming(programming_id)
    if not programming:
        raise ValueError("Запись программирования не найдена.")
    credentials = uk_repository.get_group_credentials(
        int(programming["uk_group_id"])
    )
    if not credentials:
        raise ValueError("Управляющая компания не найдена.")

    crm_call = (
        crm_add_key_for_company
        if operation == "add"
        else crm_remove_key_for_company
    )
    result = crm_call(
        programming["mac"],
        programming["hex_value"],
        programming["apartment"],
        0,
        login=credentials.get("crm_login", ""),
        password=credentials.get("crm_password", ""),
    )
    safe_response = _safe_response(result.get("response", ""), credentials)
    normalized_status = _result_status(result)
    operation_token = uuid4().hex
    uk_repository.record_crm_result(
        programming_id,
        operation=operation,
        status=normalized_status,
        idempotency_key=operation_token,
        safe_response=safe_response,
        requested_by=_actor(request),
    )

    action = (
        "uk_key_program"
        if operation == "add"
        else "uk_key_remove_from_panel"
    )
    log_event(
        request=request,
        action=action,
        object_type="Ключ УК",
        object_name=f"№{programming['number']}",
        status=result.get("status", normalized_status),
        details=(
            f"{programming['address']} / "
            f"{programming['entrance'] or programming['panel_name']} / "
            f"кв. {programming['apartment']}"
        ),
        printed_number=programming["number"],
        hex_value=programming["hex_value"],
        flat_num=programming["apartment"],
        mac=programming["mac"],
        panel_name=programming["panel_name"],
        address=programming["address"],
        apartment=programming["apartment"],
        panel_id=programming["panel_id"],
        response=safe_response,
        key_id=programming["key_id"],
        uk_group_id=programming["uk_group_id"],
    )
    return {
        **result,
        "response": safe_response,
        "programming_id": programming_id,
    }


def issue_key(
    *,
    group_id: int,
    key_id: int,
    panel_link_id: int | None = None,
    panel_link_ids: list[int] | None = None,
    apartment_override: str = "",
    override_confirmed: bool = False,
    comment: str = "",
    request=None,
    training_mode: bool = False,
) -> dict:
    selected_link_ids = list(dict.fromkeys(
        int(value)
        for value in (panel_link_ids or ([panel_link_id] if panel_link_id else []))
        if value
    ))
    if not selected_link_ids:
        raise ValueError("Выберите хотя бы одну панель УК.")
    available_links = {
        int(item["link_id"]): item
        for item in uk_repository.get_group_panels(group_id)
    }
    if any(link_id not in available_links for link_id in selected_link_ids):
        raise ValueError("Одна или несколько выбранных панелей не закреплены за этой УК.")
    override = (apartment_override or "").strip()
    for link_id in selected_link_ids:
        registered = str(available_links[link_id].get("apartment") or "").strip()
        if override and override != registered and not override_confirmed:
            raise ValueError("Изменение квартиры только для операции требует подтверждения.")
        if not (override or registered):
            raise ValueError("Для одной из выбранных панелей не указана квартира УК.")
    if training_mode:
        return {
            "ok": True,
            "status": "TRAINING_MODE",
            "response": "Учебный режим: база и CRM не изменялись",
        }
    issue_id, programming_id = uk_repository.create_key_issue(
        group_id,
        key_id,
        selected_link_ids[0],
        apartment_override=apartment_override,
        override_confirmed=override_confirmed,
        comment=comment,
        issued_by=_actor(request),
    )
    programming_ids = [programming_id]
    for link_id in selected_link_ids[1:]:
        programming_ids.append(uk_repository.create_programming(
            group_id,
            issue_id,
            link_id,
            apartment_override=apartment_override,
            override_confirmed=override_confirmed,
        ))

    results: list[dict] = []
    for link_id, current_id in zip(selected_link_ids, programming_ids):
        try:
            panel_result = _run_programming(current_id, operation="add", request=request)
        except Exception as error:
            safe_error = _safe_response(str(error))
            uk_repository.record_crm_result(
                current_id,
                operation="add",
                status="error",
                idempotency_key=uuid4().hex,
                safe_response=safe_error,
                requested_by=_actor(request),
            )
            panel_result = {
                "ok": False,
                "status": "ERROR",
                "response": safe_error,
                "programming_id": current_id,
            }
        results.append({**panel_result, "panel_link_id": link_id})

    success_count = sum(bool(item.get("ok")) for item in results)
    if results and all(item.get("status") == "DRY_RUN" for item in results):
        status = "DRY_RUN"
    else:
        status = "SUCCESS" if success_count == len(results) else ("PARTIAL" if success_count else "ERROR")
    return {
        "ok": success_count == len(results),
        "status": status,
        "issue_id": issue_id,
        "programming_id": programming_ids[0],
        "results": results,
        "success_count": success_count,
        "error_count": len(results) - success_count,
    }


def add_master_panel(
    *,
    group_id: int,
    issue_id: int,
    panel_link_id: int,
    apartment_override: str = "",
    override_confirmed: bool = False,
    request=None,
    training_mode: bool = False,
) -> dict:
    if training_mode:
        return {
            "ok": True,
            "status": "TRAINING_MODE",
            "response": "Учебный режим: база и CRM не изменялись",
        }
    programming_id = uk_repository.create_programming(
        group_id,
        issue_id,
        panel_link_id,
        apartment_override=apartment_override,
        override_confirmed=override_confirmed,
    )
    return _run_programming(
        programming_id,
        operation="add",
        request=request,
    )


def retry_programming(
    programming_id: int,
    *,
    request=None,
    training_mode: bool = False,
) -> dict:
    if training_mode:
        return {
            "ok": True,
            "status": "TRAINING_MODE",
            "response": "Учебный режим: запрос в CRM не отправлялся",
        }
    return _run_programming(
        programming_id,
        operation="add",
        request=request,
    )


def remove_from_crm(
    programming_id: int,
    *,
    request=None,
    training_mode: bool = False,
) -> dict:
    if training_mode:
        return {
            "ok": True,
            "status": "TRAINING_MODE",
            "response": "Учебный режим: запрос в CRM не отправлялся",
        }
    return _run_programming(
        programming_id,
        operation="remove",
        request=request,
    )


def unlink_accounting(programming_id: int, *, request=None) -> None:
    programming = uk_repository.get_programming(programming_id)
    if not programming:
        raise ValueError("Запись программирования не найдена.")
    uk_repository.unlink_programming(programming_id)
    log_event(
        request=request,
        action="uk_key_unlink",
        object_type="Ключ УК",
        object_name=f"№{programming['number']}",
        status="warning",
        details=(
            "Удалена только учётная связь. "
            "Запрос удаления ключа из CRM не выполнялся."
        ),
        printed_number=programming["number"],
        hex_value=programming["hex_value"],
        panel_id=programming["panel_id"],
        mac=programming["mac"],
        panel_name=programming["panel_name"],
        address=programming["address"],
        apartment=programming["apartment"],
        key_id=programming["key_id"],
        uk_group_id=programming["uk_group_id"],
    )
