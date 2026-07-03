from app.db import db


def log_event(
    *,
    request,
    mode: str,
    status: str = "success",
    printed_number: str = "",
    hex_value: str = "-",
    flat_num: str = "",
    mac: str = "",
    panel_name: str = "",
    address: str = "",
    apartment: str = "",
    response: str = "",
):
    user = request.session.get("user", {}) if request else {}

    with db() as conn:
        conn.execute(
            """
            INSERT INTO operation_log(
                mode,
                printed_number,
                hex_value,
                flat_num,
                mac,
                panel_name,
                status,
                response,
                address,
                apartment,
                username,
                user_full_name,
                user_role
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                mode,
                printed_number,
                hex_value,
                flat_num,
                mac,
                panel_name,
                status,
                response,
                address,
                apartment,
                user.get("login", ""),
                user.get("full_name", ""),
                user.get("role", ""),
            ),
        )