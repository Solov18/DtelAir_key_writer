from app.db import db
from app.repositories.log_repository import normalize_operation_row
from app.repositories.key_repository import get_keys_page
from app.services.keys import find_keys, normalize_hex_value


def universal_search(query: str):
    query = (query or "").strip()
    hex_value = normalize_hex_value(query)

    result = {
        "query": query,
        "key": None,
        "last_operation": None,
        "history": [],
        "address_results": [],
        "inventory_results": [],
    }

    if not query:
        return result

    key_matches = find_keys(query)
    key = key_matches[0] if len(key_matches) == 1 else None
    result["key"] = key
    result["inventory_results"] = get_keys_page(
        query=query,
        page=1,
        page_size=50,
    )["items"]

    with db() as conn:
        if key:
            history = [
                normalize_operation_row(dict(row))
                for row in conn.execute(
                    """
                    SELECT *
                    FROM operation_log
                    WHERE key_id = ?
                       OR (
                            key_id IS NULL
                            AND printed_number = ?
                            AND UPPER(hex_value) = ?
                       )
                    ORDER BY id DESC
                    LIMIT 50
                    """,
                    (
                        key.get("id"),
                        key.get("number", ""),
                        key.get("hex_value", "").upper(),
                    ),
                )
            ]

            result["history"] = history
            result["last_operation"] = history[0] if history else None

        result["address_results"] = [
            normalize_operation_row(dict(row))
            for row in conn.execute(
                """
                SELECT *
                FROM operation_log
                WHERE address LIKE ?
                   OR apartment LIKE ?
                   OR flat_num LIKE ?
                   OR printed_number LIKE ?
                   OR UPPER(hex_value) LIKE ?
                ORDER BY id DESC
                LIMIT 50
                """,
                (
                    f"%{query}%",
                    f"%{query}%",
                    f"%{query}%",
                    f"%{query}%",
                    f"%{hex_value}%",
                ),
            )
        ]

    return result
