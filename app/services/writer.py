import json
import logging
from contextlib import contextmanager
from threading import BoundedSemaphore

import requests
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from app.db import db, get_engine
from app.repositories.key_repository import get_key_write_contexts, set_key_assignment
from app.services.crm import crm_add_key


logger = logging.getLogger("uvicorn.error")


UNAVAILABLE_KEY_STATUSES = {
    "blocked": "Ключ заблокирован",
    "lost": "Ключ отмечен как утерянный",
    "defective": "Ключ отмечен как брак",
    "archived": "Ключ находится в архиве",
}
_WRITE_LOCK_CONNECTIONS = BoundedSemaphore(2)


@contextmanager
def _serialized_key_write(key_id: int | None):
    """Serialize one physical key operation across all FastAPI workers."""

    if not key_id:
        yield
        return
    # Keep the value in PostgreSQL's signed bigint range and outside the
    # monitor's fixed advisory-lock identifier.
    lock_id = ((int(key_id) & 0x7FFFFFFF) << 32) | 0x4B4559
    # The advisory lock uses a dedicated non-pooled connection. Holding a
    # regular pool slot while repositories open their own transactions could
    # otherwise exhaust a small pool under concurrent writes.
    with _WRITE_LOCK_CONNECTIONS:
        lock_engine = create_engine(get_engine().url, poolclass=NullPool)
        try:
            with lock_engine.connect() as lock_connection:
                lock_connection.execute(
                    text("SELECT pg_advisory_lock(:lock_id)"),
                    {"lock_id": lock_id},
                )
                try:
                    yield
                finally:
                    lock_connection.execute(
                        text("SELECT pg_advisory_unlock(:lock_id)"),
                        {"lock_id": lock_id},
                    )
        finally:
            lock_engine.dispose()


def _write_key_to_panels_unlocked(
    mode: str,
    key_item: dict,
    panels: list[dict],
    flat_num="0",
    inner=1,
    address="",
    request=None,
    assignment_type: str = "",
    employee_id: int | None = None,
    uk_group_id: int | None = None,
    assignment_policy: str = "replace",
    known_panel_ids: set[int] | None = None,
    write_option: str = "",
    previous_assignment: str = "",
    automatic_panel_ids: set[int] | None = None,
    manual_panel_ids: set[int] | None = None,
):
    results = []
    known_panel_ids = {int(value) for value in (known_panel_ids or set())}
    selected_panel_ids = [int(panel["id"]) for panel in panels if panel.get("id")]
    automatic_panel_ids = {
        int(value) for value in (automatic_panel_ids or set())
        if int(value) in selected_panel_ids
    }
    manual_panel_ids = {
        int(value) for value in (manual_panel_ids or set())
        if int(value) in selected_panel_ids and int(value) not in automatic_panel_ids
    }

    user = request.session.get("user", {}) if request else {}
    training_mode = bool(
        request and request.session.get("training_mode")
    )

    ip_address = ""
    if request and request.client:
        ip_address = request.client.host

    logger.info(
        "key_write.start mode=%s key_id=%s panels=%s panel_ids=%s",
        mode,
        key_item.get("id"),
        len(panels),
        [panel.get("id") for panel in panels],
    )

    for panel in panels:
        panel_id = panel.get("id")
        logger.info(
            "key_write.panel.start key_id=%s panel_id=%s mac=%s",
            key_item.get("id"),
            panel_id,
            panel.get("mac", ""),
        )
        if panel_id and int(panel_id) in known_panel_ids:
            results.append(
                {
                    "panel": panel,
                    "flat_num": str(flat_num or ""),
                    "ok": True,
                    "written": False,
                    "status": "ALREADY_ON_PANEL",
                    "response": "Ключ уже записан на этой панели — повторный запрос не отправлялся",
                    "message": "Ключ уже записан на этой панели",
                    "persisted": True,
                }
            )
            logger.info(
                "key_write.panel.skip_existing key_id=%s panel_id=%s",
                key_item.get("id"),
                panel_id,
            )
            continue

        unavailable_reason = (
            "У ключа не указан HEX"
            if not (key_item.get("hex_value") or "").strip()
            else "У панели не указан MAC"
            if not (panel.get("mac") or "").strip()
            else UNAVAILABLE_KEY_STATUSES.get(key_item.get("status", ""))
        )
        if training_mode:
            result = (
                {
                    "ok": False,
                    "written": False,
                    "status": "KEY_UNAVAILABLE",
                    "response": unavailable_reason,
                    "message": unavailable_reason,
                }
                if unavailable_reason
                else {
                    "ok": True,
                    "written": False,
                    "status": "TRAINING_MODE",
                    "response": (
                        "Учебная проверка выполнена. "
                        "Запрос в CRM не отправлялся, база и журнал не изменены."
                    ),
                    "message": "Безопасная имитация записи",
                }
            )
            results.append(
                {
                    "panel": panel,
                    "flat_num": str(flat_num or ""),
                    **result,
                }
            )
            continue
        elif unavailable_reason:
            result = {
                "ok": False,
                "written": False,
                "status": "KEY_UNAVAILABLE",
                "response": unavailable_reason,
                "message": unavailable_reason,
            }
        else:
            try:
                result = crm_add_key(
                    panel["mac"],
                    key_item["hex_value"],
                    flat_num,
                    inner,
                )
                if not isinstance(result, dict):
                    raise ValueError("CRM вернула ответ неизвестного формата")
                required_fields = {"status", "response", "written", "ok"}
                if not required_fields.issubset(result):
                    raise ValueError("CRM вернула неполный результат операции")
            except (requests.Timeout, TimeoutError):
                result = {
                    "ok": False,
                    "written": False,
                    "status": "TIMEOUT",
                    "response": "Превышено время ожидания ответа панели",
                    "message": "Превышено время ожидания ответа панели",
                }
            except Exception:
                logger.exception(
                    "key_write.panel.request_error key_id=%s panel_id=%s",
                    key_item.get("id"),
                    panel_id,
                )
                result = {
                    "ok": False,
                    "written": False,
                    "status": "ERROR",
                    "response": "Не удалось обработать ответ панели",
                    "message": "Не удалось обработать ответ панели",
                }

        logger.info(
            "key_write.panel.response key_id=%s panel_id=%s status=%s written=%s",
            key_item.get("id"),
            panel_id,
            result.get("status"),
            bool(result.get("written")),
        )

        try:
            logger.info(
                "key_write.panel.persist key_id=%s panel_id=%s",
                key_item.get("id"),
                panel_id,
            )
            with db() as conn:
                conn.execute(
                    """
                    INSERT INTO operation_log(
                        mode,
                        action,
                        object_type,
                        object_name,
                        details,
                        printed_number,
                        hex_value,
                        flat_num,
                        panel_id,
                        mac,
                        panel_name,
                        status,
                        response,
                        address,
                        apartment,
                        username,
                        user_full_name,
                        user_role,
                        ip_address,
                        key_id,
                        key_type,
                        employee_id,
                        uk_group_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        mode,
                        write_option or mode,
                        "Ключ",
                        key_item.get("number", "") or key_item.get("hex_value", ""),
                        json.dumps(
                            {
                                "write_option": write_option or mode,
                                "previous_assignment": previous_assignment,
                                "target_address": address,
                                "target_apartment": str(flat_num or ""),
                                "panel_id": panel.get("id"),
                                "panel_name": panel.get("name", ""),
                            },
                            ensure_ascii=False,
                        ),
                        key_item.get("number", ""),
                        key_item["hex_value"],
                        str(flat_num),
                        panel.get("id"),
                        panel["mac"],
                        panel.get("name", ""),
                        result["status"],
                        result["response"],
                        address or panel.get("address", ""),
                        str(flat_num),
                        user.get("login", ""),
                        user.get("full_name", ""),
                        user.get("role", ""),
                        ip_address,
                        key_item.get("id"),
                        key_item.get("type_name") or key_item.get("key_type", ""),
                        employee_id,
                        uk_group_id,
                    ),
                )
        except Exception:
            logger.exception(
                "key_write.panel.persist_error key_id=%s panel_id=%s",
                key_item.get("id"),
                panel_id,
            )
            result = {
                **result,
                "persisted": False,
                "persistence_error": "Результат панели не удалось записать в журнал",
            }
        else:
            result = {**result, "persisted": True}

        results.append(
            {
                "panel": panel,
                "flat_num": str(flat_num or ""),
                **result,
            }
        )

    written = any(result.get("written") for result in results)
    confirmed_access = any(
        result.get("written")
        or result.get("status") in {"ALREADY_EXISTS", "ALREADY_ON_PANEL"}
        for result in results
    )
    key_id = key_item.get("id")

    if confirmed_access and key_id and assignment_policy == "replace":
        resolved_assignment_type = assignment_type
        if not resolved_assignment_type:
            if mode in {"resident", "resident_manual", "message"}:
                resolved_assignment_type = "resident"
            elif mode == "employee":
                resolved_assignment_type = "employee"
            elif mode == "uk":
                resolved_assignment_type = "uk"

        if resolved_assignment_type:
            try:
                logger.info("key_write.assignment.persist key_id=%s", key_id)
                set_key_assignment(
                    int(key_id),
                    resolved_assignment_type,
                    address=address,
                    apartment=str(flat_num or ""),
                    employee_id=employee_id,
                    uk_group_id=uk_group_id,
                    assigned_by=(
                        user.get("full_name")
                        or user.get("login")
                        or "Система"
                    ),
                )
            except Exception:
                logger.exception("key_write.assignment.persist_error key_id=%s", key_id)
                for result in results:
                    if result.get("written"):
                        result["assignment_error"] = (
                            "Ключ записан, но назначение не удалось сохранить в CRM"
                        )

    if key_id and not training_mode:
        successes = [
            result for result in results
            if result.get("written")
            or result.get("status") in {"ALREADY_EXISTS", "ALREADY_ON_PANEL"}
        ]
        failures = [result for result in results if result not in successes]
        summary_status = (
            "SUCCESS" if successes and not failures
            else "WARNING" if successes
            else "ERROR"
        )
        newly_written_panel_ids = [
            int(result["panel"]["id"])
            for result in results
            if result.get("written") and result.get("panel", {}).get("id")
        ]
        summary_details = json.dumps(
            {
                "write_option": write_option or mode,
                "previous_assignment": previous_assignment,
                "new_assignment": (
                    {"type": assignment_type or "resident", "address": address, "apartment": str(flat_num or "")}
                    if assignment_policy == "replace" and confirmed_access
                    else None
                ),
                "old_panel_ids": sorted(known_panel_ids),
                "selected_panel_ids": selected_panel_ids,
                "automatic_panel_ids": sorted(automatic_panel_ids),
                "manual_panel_ids": sorted(manual_panel_ids),
                "new_panel_ids": newly_written_panel_ids,
                "successful_panel_ids": [
                    int(result["panel"]["id"])
                    for result in successes
                    if result.get("panel", {}).get("id")
                ],
                "failed_panel_ids": [
                    int(result["panel"]["id"])
                    for result in failures
                    if result.get("panel", {}).get("id")
                ],
            },
            ensure_ascii=False,
        )
        try:
            with db() as conn:
                conn.execute(
                    """
                    INSERT INTO operation_log(
                        mode, action, object_type, object_name, details,
                        printed_number, hex_value, mac, status, response,
                        address, apartment, username, user_full_name, user_role,
                        ip_address, key_id, key_type, employee_id, uk_group_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"{mode}_decision",
                        "key_write_decision",
                        "Ключ",
                        key_item.get("number", "") or key_item.get("hex_value", ""),
                        summary_details,
                        key_item.get("number", ""),
                        key_item.get("hex_value", ""),
                        summary_status,
                        (
                            f"Успешно: {len(successes)}; ошибок: {len(failures)}; "
                            f"новых записей: {len(newly_written_panel_ids)}"
                        ),
                        address,
                        str(flat_num or ""),
                        user.get("login", ""),
                        user.get("full_name", ""),
                        user.get("role", ""),
                        ip_address,
                        key_id,
                        key_item.get("type_name") or key_item.get("key_type", ""),
                        employee_id,
                        uk_group_id,
                    ),
                )
        except Exception:
            logger.exception("key_write.summary.persist_error key_id=%s", key_id)

    logger.info(
        "key_write.finish key_id=%s success=%s errors=%s",
        key_item.get("id"),
        sum(
            1
            for result in results
            if result.get("written")
            or result.get("status") in {"ALREADY_EXISTS", "ALREADY_ON_PANEL"}
        ),
        sum(
            1
            for result in results
            if not result.get("written")
            and result.get("status") not in {"ALREADY_EXISTS", "ALREADY_ON_PANEL"}
        ),
    )

    return results


def write_key_to_panels(
    mode: str,
    key_item: dict,
    panels: list[dict],
    flat_num="0",
    inner=1,
    address="",
    request=None,
    assignment_type: str = "",
    employee_id: int | None = None,
    uk_group_id: int | None = None,
    assignment_policy: str = "replace",
    known_panel_ids: set[int] | None = None,
    write_option: str = "",
    previous_assignment: str = "",
    automatic_panel_ids: set[int] | None = None,
    manual_panel_ids: set[int] | None = None,
):
    """Write one key safely, including when several web workers race."""

    key_id = int(key_item["id"]) if key_item.get("id") else None
    with _serialized_key_write(key_id):
        refreshed_known = set(known_panel_ids or set())
        if key_id:
            context = get_key_write_contexts([key_id]).get(key_id, {})
            refreshed_known.update(int(value) for value in context.get("panel_ids", []))
        return _write_key_to_panels_unlocked(
            mode,
            key_item,
            panels,
            flat_num=flat_num,
            inner=inner,
            address=address,
            request=request,
            assignment_type=assignment_type,
            employee_id=employee_id,
            uk_group_id=uk_group_id,
            assignment_policy=assignment_policy,
            known_panel_ids=refreshed_known,
            write_option=write_option,
            previous_assignment=previous_assignment,
            automatic_panel_ids=automatic_panel_ids,
            manual_panel_ids=manual_panel_ids,
        )
