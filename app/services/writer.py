from app.db import db
from app.repositories.key_repository import set_key_assignment
from app.services.crm import crm_add_key


UNAVAILABLE_KEY_STATUSES = {
    "blocked": "Ключ заблокирован",
    "lost": "Ключ отмечен как утерянный",
    "defective": "Ключ отмечен как брак",
    "archived": "Ключ находится в архиве",
}


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
):
    results = []

    user = request.session.get("user", {}) if request else {}
    training_mode = bool(
        request and request.session.get("training_mode")
    )

    ip_address = ""
    if request and request.client:
        ip_address = request.client.host

    for panel in panels:
        unavailable_reason = (
            "У ключа не указан HEX"
            if not (key_item.get("hex_value") or "").strip()
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
            result = crm_add_key(
                panel["mac"],
                key_item["hex_value"],
                flat_num,
                inner,
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
                    mode,
                    "Ключ",
                    key_item.get("number", "") or key_item.get("hex_value", ""),
                    f"{address or panel.get('address', '')} / кв. {flat_num} / {panel.get('name', '')} / {panel['mac']}",
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

        results.append(
            {
                "panel": panel,
                "flat_num": str(flat_num or ""),
                **result,
            }
        )

    written = any(result.get("written") for result in results)
    key_id = key_item.get("id")

    if written and key_id:
        resolved_assignment_type = assignment_type
        if not resolved_assignment_type:
            if mode in {"resident", "resident_manual", "message"}:
                resolved_assignment_type = "resident"
            elif mode == "employee":
                resolved_assignment_type = "employee"
            elif mode == "uk":
                resolved_assignment_type = "uk"

        if resolved_assignment_type:
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

    return results
