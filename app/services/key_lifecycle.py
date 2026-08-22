"""Coordinated write/release lifecycle for local and external key state."""

import logging
from copy import deepcopy

from app.repositories import key_access_repository
from app.repositories import key_lifecycle_repository as lifecycle_repo
from app.repositories import key_repository
from app.repositories import uk_repository
from app.services.audit import log_event
from app.services.crm import crm_remove_key, crm_remove_key_for_company


logger = logging.getLogger("uvicorn.error")
IDEMPOTENT_DELETE_STATUSES = {"SUCCESS", "NOT_FOUND", "ALREADY_ABSENT"}
IDEMPOTENT_WRITE_STATUSES = {"SUCCESS", "ALREADY_EXISTS", "ALREADY_ON_PANEL"}


def record_write_result(
    *, key_id: int, panel: dict, result: dict, flat_num: str = "0",
    inner: int = 1, uk_group_id: int | None = None,
) -> None:
    if not lifecycle_repo.can_record_panel_state(key_id, int(panel["id"])):
        # Some presentation/unit callers intentionally use synthetic objects.
        # A real request can only reach here with persisted FK-backed entities.
        return
    status = str(result.get("status") or "ERROR")
    confirmed = bool(result.get("written")) or status in {
        "SUCCESS", "ALREADY_EXISTS", "ALREADY_ON_PANEL"
    }
    lifecycle_repo.record_panel_result(
        key_id=key_id,
        panel_id=int(panel["id"]),
        operation="write",
        status=status,
        success=confirmed,
        flat_num=str(flat_num or "0"),
        inner=inner,
        uk_group_id=uk_group_id,
        error="" if confirmed else str(result.get("response") or "Ошибка записи"),
    )


def _operation_snapshot(operation: dict) -> dict:
    return deepcopy(operation["assignment_snapshot"])


def _execute_delete_phase(operation: dict, *, request=None) -> list[dict]:
    """Delete only unfinished panel steps from the persisted snapshot."""
    operation_id = int(operation["id"])
    snapshot = _operation_snapshot(operation)
    panel_by_id = {int(panel["panel_id"]): panel for panel in snapshot.get("panels", [])}
    panel_ids = [int(value) for value in operation.get("source_panel_ids", [])]
    lifecycle_repo.ensure_operation_steps(operation_id, panel_ids, "delete_old")
    lifecycle_repo.set_operation_status(operation_id, "deleting")
    results = []
    for step in lifecycle_repo.get_operation_steps(operation_id, "delete_old"):
        if step["state"] == "success":
            continue
        panel = panel_by_id.get(int(step["panel_id"]))
        if not panel:
            lifecycle_repo.record_step_result(
                int(step["id"]), success=False, status="ERROR",
                error="Панель отсутствует в сохранённом snapshot операции",
            )
            results.append({"panel_id": step["panel_id"], "success": False, "status": "ERROR"})
            continue
        lifecycle_repo.mark_step_running(int(step["id"]))
        try:
            credentials = None
            if panel.get("uk_group_id"):
                credentials = uk_repository.get_group_credentials(int(panel["uk_group_id"]))
                if not credentials:
                    raise ValueError("Не найдены реквизиты CRM управляющей компании")

            # The existing central-CRM contract receives the panel MAC, HEX
            # and the apartment stored at write time. crm.dtel.ru owns any
            # propagation to the physical device; this service never calls a
            # panel device API directly.
            if credentials:
                result = crm_remove_key_for_company(
                    panel["mac"], snapshot["hex_value"], panel.get("flat_num") or "0",
                    panel["is_inner"], login=credentials.get("crm_login", ""),
                    password=credentials.get("crm_password", ""),
                )
            else:
                result = crm_remove_key(
                    panel["mac"], snapshot["hex_value"], panel.get("flat_num") or "0",
                    panel["is_inner"],
                )
        except Exception as error:
            logger.exception(
                "key_lifecycle.release.panel_error operation_id=%s key_id=%s panel_id=%s",
                operation_id, snapshot["id"], panel["panel_id"],
            )
            result = {"ok": False, "status": "ERROR", "response": str(error)}
        status = str(result.get("status") or "ERROR")
        success = (bool(result.get("ok")) or status in IDEMPOTENT_DELETE_STATUSES) and status != "DRY_RUN"
        error = "" if success else str(result.get("response") or "Ошибка удаления")
        lifecycle_repo.record_panel_result(
            key_id=int(snapshot["id"]), panel_id=int(panel["panel_id"]),
            operation="delete", status=status, success=success,
            flat_num=panel["flat_num"], inner=int(panel["is_inner"]),
            uk_group_id=panel.get("uk_group_id"), error=error,
        )
        lifecycle_repo.record_step_result(
            int(step["id"]), success=success, status=status, error=error, payload=result,
        )
        results.append({"panel": panel, **result, "success": success})
        log_event(
            request=request, action="key_panel_delete", object_type="Ключ",
            object_name=str(snapshot.get("number") or snapshot["id"]),
            status="success" if success else "error",
            details="Удаление записи ключа из CRM перед локальным освобождением",
            response=str(result.get("response") or status),
            printed_number=str(snapshot.get("number") or ""),
            hex_value=str(snapshot.get("hex_value") or "-"),
            flat_num=str(panel.get("flat_num") or "0"), mac=str(panel.get("mac") or ""),
            panel_name=str(panel.get("panel_name") or panel.get("entrance") or ""),
            address=str(panel.get("address") or ""), panel_id=int(panel["panel_id"]),
            key_id=int(snapshot["id"]), key_type=str(snapshot.get("type_name") or ""),
            uk_group_id=panel.get("uk_group_id"),
        )
    return results


def _delete_phase_complete(operation_id: int) -> bool:
    return all(
        step["state"] == "success"
        for step in lifecycle_repo.get_operation_steps(operation_id, "delete_old")
    )


def release_key(
    key_id: int, *, reason: str = "Ключ освобождён", final_status: str = "free",
    employee_assignment_status: str = "inactive", request=None,
    operation_scope: str = "release", target_context: dict | None = None,
) -> dict:
    if final_status not in {"free", "lost", "defective", "blocked", "archived"}:
        raise ValueError("Некорректный конечный статус ключа.")
    if employee_assignment_status not in {"inactive", "replaced", "lost", "damaged", "dismissed"}:
        raise ValueError("Некорректный статус истории ключа сотрудника.")
    current_snapshot = lifecycle_repo.get_key_snapshot(key_id)
    if not current_snapshot:
        raise ValueError("Ключ не найден.")
    current_snapshot = deepcopy(current_snapshot)
    current_snapshot["_lifecycle_scope"] = operation_scope
    current_snapshot["_target_context"] = target_context or {}
    operation_type = operation_scope if operation_scope in {"release", "reassign"} else "release"
    operation = lifecycle_repo.create_or_resume_operation(
        operation_type=operation_type, old_key_id=key_id, new_key_id=None, reason=reason,
        final_old_status=final_status,
        employee_assignment_status=employee_assignment_status,
        snapshot=current_snapshot,
    )
    snapshot = _operation_snapshot(operation)
    panel_ids = [int(value) for value in operation["source_panel_ids"]]
    lifecycle_repo.mark_panels_pending_delete(key_id, panel_ids)
    logger.info("key_lifecycle.release.start operation_id=%s key_id=%s panels=%s", operation["id"], key_id, panel_ids)
    results = _execute_delete_phase(operation, request=request)

    if not _delete_phase_complete(int(operation["id"])):
        steps = lifecycle_repo.get_operation_steps(int(operation["id"]), "delete_old")
        failures = [step for step in steps if step["state"] != "success"]
        completed = len(steps) - len(failures)
        lifecycle_status = "PARTIAL" if completed else "ERROR"
        lifecycle_repo.set_operation_status(
            int(operation["id"]), "partial" if completed else "error",
            f"Незавершённых панелей: {len(failures)}",
        )
        logger.warning(
            "key_lifecycle.release.partial operation_id=%s key_id=%s failed_panel_ids=%s",
            operation["id"], key_id, [item["panel_id"] for item in failures],
        )
        log_event(
            request=request,
            action="key_release",
            object_type="Ключ",
            object_name=str(snapshot.get("number") or key_id),
            status="warning" if lifecycle_status == "PARTIAL" else "error",
            details=f"Локальное освобождение не выполнено: {len(failures)} записей ключа не удалены из CRM",
            printed_number=str(snapshot.get("number") or ""),
            hex_value=str(snapshot.get("hex_value") or "-"),
            key_id=key_id,
            key_type=str(snapshot.get("type_name") or ""),
        )
        return {"ok": False, "status": lifecycle_status, "operation_id": operation["id"], "results": results, "snapshot": snapshot}

    resumed_write_phase = (
        operation_type == "reassign"
        and operation.get("status") in {"writing", "partial", "error"}
        and bool(lifecycle_repo.get_operation_steps(int(operation["id"]), "write_new"))
    )
    if not resumed_write_phase:
        lifecycle_repo.finalize_release(
            key_id, final_status=operation["final_old_status"], reason=operation["reason"],
            employee_assignment_status=operation["employee_assignment_status"],
        )
    log_event(
        request=request,
        action="key_release",
        object_type="Ключ",
        object_name=str(snapshot.get("number") or key_id),
        status="success",
        details=f"Ключ освобождён после подтверждённого удаления {len(panel_ids)} записей из CRM. Причина: {operation['reason']}",
        printed_number=str(snapshot.get("number") or ""),
        hex_value=str(snapshot.get("hex_value") or "-"),
        key_id=key_id,
        key_type=str(snapshot.get("type_name") or ""),
    )
    lifecycle_repo.set_operation_status(
        int(operation["id"]),
        "writing" if operation_type == "reassign" else "completed",
    )
    logger.info("key_lifecycle.release.finish operation_id=%s key_id=%s status=%s", operation["id"], key_id, operation["final_old_status"])
    return {"ok": True, "status": "SUCCESS", "operation_id": operation["id"], "results": results, "snapshot": snapshot}


def reassign_key(
    key_id: int, *, write_callback, reason: str, request=None,
    target_context: dict | None = None,
) -> dict:
    """Delete the old external access before writing a new assignment."""
    released = release_key(
        key_id, reason=reason, final_status="free", request=request,
        operation_scope="reassign", target_context=target_context,
    )
    if not released["ok"]:
        return {
            "ok": False, "status": released["status"], "release": released,
            "write": None, "snapshot": released["snapshot"],
        }

    operation_id = int(released["operation_id"])
    target_panel_ids = sorted({
        int(value) for value in (target_context or {}).get("panel_ids", [])
    })
    lifecycle_repo.ensure_operation_steps(operation_id, target_panel_ids, "write_new")
    pending_steps = [
        step for step in lifecycle_repo.get_operation_steps(operation_id, "write_new")
        if step["state"] != "success"
    ]
    pending_ids = [int(step["panel_id"]) for step in pending_steps]
    for step in pending_steps:
        lifecycle_repo.mark_step_running(int(step["id"]))
    written = write_callback(released["snapshot"], pending_ids) if pending_steps else []
    values = written if isinstance(written, list) else []
    result_by_panel = {
        int(item.get("panel", {}).get("id")): item
        for item in values if item.get("panel", {}).get("id") is not None
    }
    for step in pending_steps:
        item = result_by_panel.get(int(step["panel_id"]))
        status = str((item or {}).get("status") or "ERROR")
        success = bool((item or {}).get("written")) or status in IDEMPOTENT_WRITE_STATUSES
        success = success and (item or {}).get("persisted") is not False
        lifecycle_repo.record_step_result(
            int(step["id"]), success=success, status=status,
            error="" if success else str((item or {}).get("response") or "Нет результата записи"),
            payload=item or {},
        )
    remaining = [
        step for step in lifecycle_repo.get_operation_steps(operation_id, "write_new")
        if step["state"] != "success"
    ]
    completed = len(target_panel_ids) - len(remaining)
    status = "SUCCESS" if target_panel_ids and not remaining else "PARTIAL" if completed else "ERROR"
    lifecycle_repo.set_operation_status(
        operation_id,
        "completed" if status == "SUCCESS" else "partial" if completed else "error",
        "" if status == "SUCCESS" else f"Незавершённых записей: {len(remaining)}",
    )
    return {
        "ok": status == "SUCCESS", "status": status, "release": released,
        "write": written, "snapshot": released["snapshot"],
        "operation_id": operation_id,
    }


def replace_key(
    old_key_id: int,
    new_key: dict,
    *,
    final_old_status: str,
    write_callback,
    reason: str,
    request=None,
) -> dict:
    """Release A first, then let the existing writer program B.

    The callback receives the exact pre-release snapshot, so address,
    apartment and panel ids cannot be reconstructed from audit text.
    """
    current_snapshot = lifecycle_repo.get_key_snapshot(old_key_id)
    if not current_snapshot:
        raise ValueError("Заменяемый ключ не найден.")
    operation = lifecycle_repo.create_or_resume_operation(
        operation_type="replace", old_key_id=old_key_id,
        new_key_id=int(new_key["id"]), reason=reason,
        final_old_status=final_old_status, employee_assignment_status="replaced",
        snapshot=current_snapshot,
    )
    snapshot = _operation_snapshot(operation)
    panel_ids = [int(value) for value in operation["source_panel_ids"]]
    lifecycle_repo.mark_panels_pending_delete(old_key_id, panel_ids)
    delete_results = _execute_delete_phase(operation, request=request)
    if not _delete_phase_complete(int(operation["id"])):
        lifecycle_repo.set_operation_status(int(operation["id"]), "partial", "Не все прежние записи ключа удалены из CRM")
        return {
            "ok": False, "status": "PARTIAL", "operation_id": operation["id"],
            "release": {"ok": False, "status": "PARTIAL", "results": delete_results, "snapshot": snapshot},
            "write": None, "snapshot": snapshot,
        }

    lifecycle_repo.finalize_release(
        old_key_id, final_status=operation["final_old_status"],
        reason=operation["reason"], employee_assignment_status="replaced",
    )
    lifecycle_repo.ensure_operation_steps(int(operation["id"]), panel_ids, "write_new")
    write_steps = lifecycle_repo.get_operation_steps(int(operation["id"]), "write_new")
    pending_steps = [step for step in write_steps if step["state"] != "success"]
    pending_ids = {int(step["panel_id"]) for step in pending_steps}
    pending_snapshot = deepcopy(snapshot)
    pending_snapshot["panels"] = [
        panel for panel in snapshot.get("panels", [])
        if int(panel["panel_id"]) in pending_ids
    ]
    lifecycle_repo.set_operation_status(int(operation["id"]), "writing")
    for step in pending_steps:
        lifecycle_repo.mark_step_running(int(step["id"]))
    written = write_callback(new_key, pending_snapshot) if pending_steps else []

    if isinstance(written, list):
        result_by_panel = {
            int(item.get("panel", {}).get("id")): item
            for item in written if item.get("panel", {}).get("id") is not None
        }
        for step in pending_steps:
            item = result_by_panel.get(int(step["panel_id"]))
            status = str((item or {}).get("status") or "ERROR")
            success = bool((item or {}).get("written")) or status in IDEMPOTENT_WRITE_STATUSES
            lifecycle_repo.record_step_result(
                int(step["id"]), success=success, status=status,
                error="" if success else str((item or {}).get("response") or "Нет результата записи"),
                payload=item or {},
            )
    else:
        overall = bool(written.get("ok")) if isinstance(written, dict) else bool(written)
        for step in pending_steps:
            lifecycle_repo.record_step_result(
                int(step["id"]), success=overall,
                status="SUCCESS" if overall else "ERROR",
                error="" if overall else "Операция записи не подтверждена",
                payload=written if isinstance(written, dict) else {},
            )

    remaining = [
        step for step in lifecycle_repo.get_operation_steps(int(operation["id"]), "write_new")
        if step["state"] != "success"
    ]
    if remaining:
        lifecycle_repo.set_operation_status(
            int(operation["id"]), "partial", f"Незавершённых записей: {len(remaining)}",
        )
        return {
            "ok": False, "status": "PARTIAL", "operation_id": operation["id"],
            "release": {"ok": True, "status": "SUCCESS", "results": delete_results},
            "write": written, "snapshot": snapshot,
        }
    primary = next(
        (item for item in snapshot.get("assignments", []) if item.get("active")),
        (snapshot.get("assignments") or [None])[0],
    )
    if primary and not (key_repository.get_key(int(new_key["id"])) or {}).get("assignment_id"):
        key_repository.set_key_assignment(
            int(new_key["id"]),
            primary.get("assignment_type") or "resident",
            address=primary.get("address") or "",
            apartment=primary.get("apartment") or "",
            employee_id=primary.get("employee_id"),
            uk_group_id=primary.get("uk_group_id"),
            note=primary.get("note") or "",
            assigned_by="Замена ключа",
        )
    key_access_repository.clone_snapshot_accesses(
        int(new_key["id"]), snapshot, created_by="Замена ключа",
    )
    lifecycle_repo.set_operation_status(int(operation["id"]), "completed")
    return {
        "ok": True, "status": "SUCCESS", "operation_id": operation["id"],
        "release": {"ok": True, "status": "SUCCESS", "results": delete_results},
        "write": written, "snapshot": snapshot,
    }
