from app.db import db
from app.services.crm import crm_add_key


def write_key_to_panels(
    mode: str,
    key_item: dict,
    panels: list[dict],
    flat_num="0",
    inner=1,
    address="",
    request=None,
):
    results = []

    user = request.session.get("user", {}) if request else {}

    ip_address = ""
    if request and request.client:
        ip_address = request.client.host

    for panel in panels:
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
                    mac,
                    panel_name,
                    status,
                    response,
                    address,
                    apartment,
                    username,
                    user_full_name,
                    user_role,
                    ip_address
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                ),
            )

        results.append(
            {
                "panel": panel,
                **result,
            }
        )

    return results