from app.db import db


def log_event(
    *,
    request,
    action: str,
    object_type: str = "",
    object_name: str = "",
    status: str = "success",
    details: str = "",
    mode: str = "",
    printed_number: str = "",
    hex_value: str = "-",
    flat_num: str = "",
    mac: str = "",
    panel_name: str = "",
    address: str = "",
    apartment: str = "",
    panel_id: int | None = None,
    response: str = "",
    key_id: int | None = None,
    key_type: str = "",
    employee_id: int | None = None,
    uk_group_id: int | None = None,
    comment: str = "",
):
    user = request.session.get("user", {}) if request else {}

    ip_address = ""
    if request and request.client:
        ip_address = request.client.host
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
                mac,
                panel_name,
                status,
                response,
                address,
                apartment,
                panel_id,
                username,
                user_full_name,
                user_role,
                ip_address,
                key_id,
                key_type,
                employee_id,
                uk_group_id,
                comment
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                mode or action,
                action,
                object_type,
                object_name,
                details,
                printed_number,
                hex_value,
                flat_num,
                mac,
                panel_name,
                status,
                response,
                address,
                apartment,
                panel_id,
                user.get("login", ""),
                user.get("full_name", ""),
                user.get("role", ""),
                ip_address,
                key_id,
                key_type,
                employee_id,
                uk_group_id,
                comment,
            ),
        )
