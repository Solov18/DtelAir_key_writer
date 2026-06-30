from app.db import db
from app.services.keys import find_key, normalize_hex_value


def universal_search(query: str):
    query = (query or "").strip()
    hex_value = normalize_hex_value(query)

    result = {
        "query": query,
        "key": None,
        "last_operation": None,
        "history": [],
        "address_results": [],
    }

    if not query:
        return result

    key = find_key(query)
    result["key"] = key

    with db() as conn:
        if key:
            history = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT *
                    FROM operation_log
                    WHERE printed_number = ?
                       OR UPPER(hex_value) = ?
                    ORDER BY id DESC
                    LIMIT 50
                    """,
                    (
                        key.get("number", ""),
                        key.get("hex_value", "").upper(),
                    ),
                )
            ]

            result["history"] = history
            result["last_operation"] = history[0] if history else None

        result["address_results"] = [
            dict(row)
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