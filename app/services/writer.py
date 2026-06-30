from app.db import db
from app.services.crm import crm_add_key


def write_key_to_panels(
    mode: str,
    key_item: dict,
    panels: list[dict],
    flat_num="0",
    inner=1,
    address="",
):
    results = []

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
                    printed_number,
                    hex_value,
                    flat_num,
                    mac,
                    panel_name,
                    status,
                    response,
                    address,
                    apartment
                )
                VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    mode,
                    key_item.get("number", ""),
                    key_item["hex_value"],
                    str(flat_num),
                    panel["mac"],
                    panel.get("name", ""),
                    result["status"],
                    result["response"],
                    address or panel.get("address", ""),
                    str(flat_num),
                ),
            )

        results.append(
            {
                "panel": panel,
                **result,
            }
        )

    return results