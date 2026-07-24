from app.db import db
from app.repositories.log_repository import normalize_operation_row
from app.repositories.key_repository import get_keys_page
from app.repositories.panel_repository import normalize_panel_row
from app.search_utils import (
    matches_search,
    normalize_search_text,
    rank_search_candidates,
    search_score,
)
from app.services.keys import find_keys, normalize_hex_value


def get_search_suggestions(
    query: str,
    scope: str = "universal",
    limit: int = 8,
) -> list[dict]:
    query = (query or "").strip()
    normalized_query = normalize_search_text(query)
    if len(normalized_query) < 2:
        return []

    supported_scopes = {
        "universal",
        "employees",
        "keys",
        "panels",
        "uk",
        "log",
    }
    scope = scope if scope in supported_scopes else "universal"
    pattern = f"%{normalized_query}%"
    candidates: list[dict] = []

    with db() as conn:
        if scope in {"universal", "employees"}:
            employee_rows = conn.execute(
                """
                SELECT
                    e.id,
                    e.full_name,
                    e.position,
                    e.department,
                    e.phone,
                    e.email,
                    GROUP_CONCAT(k.number, ' ') AS key_numbers
                FROM employees e
                LEFT JOIN employee_keys ek
                    ON ek.employee_id = e.id AND ek.status = 'active'
                LEFT JOIN keys k ON k.id = ek.key_id
                WHERE e.enabled = 1
                GROUP BY e.id
                ORDER BY e.full_name COLLATE NOCASE
                LIMIT 500
                """
            ).fetchall()
            candidates.extend(
                {
                    "value": row["full_name"],
                    "label": row["full_name"],
                    "meta": " · ".join(
                        value
                        for value in (row["position"], row["department"])
                        if value
                    ) or "Сотрудник",
                    "search_text": " ".join(
                        str(row[field] or "")
                        for field in (
                            "full_name",
                            "position",
                            "department",
                            "phone",
                            "email",
                            "key_numbers",
                        )
                    ),
                }
                for row in employee_rows
            )

        if scope in {"universal", "panels"}:
            panel_rows = conn.execute(
                """
                SELECT id, address, entrance, name, mac, ip
                FROM panels
                WHERE enabled = 1
                ORDER BY address COLLATE NOCASE, entrance COLLATE NOCASE
                LIMIT 1000
                """
            ).fetchall()
            candidates.extend(
                {
                    "value": row["address"] or row["name"],
                    "label": " · ".join(
                        value
                        for value in (row["address"], row["entrance"])
                        if value
                    ),
                    "meta": f"Панель ID {row['id']} · {row['mac']}",
                    "search_text": " ".join(
                        str(row[field] or "")
                        for field in ("id", "address", "entrance", "name", "mac", "ip")
                    ),
                }
                for row in panel_rows
            )

        if scope in {"universal", "keys"}:
            key_rows = conn.execute(
                """
                SELECT
                    k.id,
                    k.number,
                    k.hex_value,
                    kt.name AS type_name,
                    e.full_name AS employee_name,
                    ka.address,
                    ka.apartment
                FROM keys k
                JOIN key_types kt ON kt.id = k.key_type_id
                LEFT JOIN key_assignments ka
                    ON ka.key_id = k.id AND ka.active = 1
                LEFT JOIN employees e ON e.id = ka.employee_id
                WHERE TRIM(k.hex_value) <> ''
                  AND (
                    SMART_NORM(k.number) LIKE ?
                    OR SMART_NORM(k.hex_value) LIKE ?
                    OR SMART_NORM(kt.name) LIKE ?
                    OR SMART_NORM(e.full_name) LIKE ?
                    OR SMART_NORM(ka.address) LIKE ?
                    OR SMART_NORM(ka.apartment) LIKE ?
                  )
                ORDER BY k.id DESC
                LIMIT 100
                """,
                [pattern] * 6,
            ).fetchall()
            candidates.extend(
                {
                    "value": row["number"],
                    "label": f"Ключ №{row['number']}",
                    "meta": f"{row['type_name']} · HEX {row['hex_value']}",
                    "search_text": " ".join(
                        str(row[field] or "")
                        for field in (
                            "number",
                            "hex_value",
                            "type_name",
                            "employee_name",
                            "address",
                            "apartment",
                        )
                    ),
                }
                for row in key_rows
            )

        if scope in {"universal", "uk"}:
            uk_rows = conn.execute(
                """
                SELECT
                    g.id,
                    g.name,
                    g.legal_name,
                    g.note,
                    g.contact_name,
                    g.phone,
                    g.email,
                    g.legal_address,
                    g.contract_number,
                    g.account_manager,
                    g.cooperation_note,
                    GROUP_CONCAT(nd.title, ' ') AS notification_titles
                FROM uk_groups g
                LEFT JOIN uk_notification_drafts nd ON nd.group_id = g.id
                WHERE
                    SMART_NORM(g.name) LIKE ?
                    OR SMART_NORM(g.legal_name) LIKE ?
                    OR SMART_NORM(g.note) LIKE ?
                    OR SMART_NORM(g.contact_name) LIKE ?
                    OR SMART_NORM(g.phone) LIKE ?
                    OR SMART_NORM(g.email) LIKE ?
                    OR SMART_NORM(g.legal_address) LIKE ?
                    OR SMART_NORM(g.contract_number) LIKE ?
                    OR SMART_NORM(g.account_manager) LIKE ?
                    OR SMART_NORM(g.cooperation_note) LIKE ?
                    OR SMART_NORM(nd.title) LIKE ?
                    OR SMART_NORM(nd.body) LIKE ?
                GROUP BY g.id
                ORDER BY g.name COLLATE NOCASE
                LIMIT 80
                """,
                [pattern] * 12,
            ).fetchall()
            candidates.extend(
                {
                    "value": row["name"],
                    "label": row["name"],
                    "meta": " · ".join(
                        value
                        for value in (
                            row["contact_name"],
                            row["phone"],
                            row["contract_number"],
                        )
                        if value
                    ) or "Управляющая компания",
                    "search_text": " ".join(
                        str(row[field] or "")
                        for field in (
                            "name",
                            "legal_name",
                            "note",
                            "contact_name",
                            "phone",
                            "email",
                            "legal_address",
                            "contract_number",
                            "account_manager",
                            "cooperation_note",
                            "notification_titles",
                        )
                    ),
                }
                for row in uk_rows
            )

        if scope in {"universal", "log"}:
            log_rows = conn.execute(
                """
                SELECT
                    action,
                    object_name,
                    details,
                    user_full_name,
                    printed_number,
                    address
                FROM operation_log
                WHERE
                    SMART_NORM(action) LIKE ?
                    OR SMART_NORM(object_name) LIKE ?
                    OR SMART_NORM(details) LIKE ?
                    OR SMART_NORM(user_full_name) LIKE ?
                    OR SMART_NORM(printed_number) LIKE ?
                    OR SMART_NORM(address) LIKE ?
                ORDER BY id DESC
                LIMIT 100
                """,
                [pattern] * 6,
            ).fetchall()
            candidates.extend(
                {
                    "value": row["object_name"] or row["printed_number"] or row["address"],
                    "label": row["object_name"] or row["details"] or row["action"],
                    "meta": row["action"] or "Операция",
                    "search_text": " ".join(str(value or "") for value in row),
                }
                for row in log_rows
                if row["object_name"] or row["printed_number"] or row["address"]
            )

    return rank_search_candidates(query, candidates, limit=limit)


def universal_search(query: str):
    query = (query or "").strip()
    hex_value = normalize_hex_value(query)
    normalized_query = normalize_search_text(query)

    result = {
        "query": query,
        "key": None,
        "last_operation": None,
        "history": [],
        "address_results": [],
        "inventory_results": [],
        "employee_results": [],
        "panel_results": [],
        "uk_results": [],
        "operation_results": [],
        "result_counts": {
            "keys": 0,
            "employees": 0,
            "panels": 0,
            "uk": 0,
            "operations": 0,
        },
    }

    if not query:
        return result
    if not normalized_query:
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

        normalized_pattern = f"%{normalized_query}%"
        result["address_results"] = [
            normalize_operation_row(dict(row))
            for row in conn.execute(
                """
                SELECT *
                FROM operation_log
                WHERE SMART_NORM(address) LIKE ?
                   OR SMART_NORM(apartment) LIKE ?
                   OR SMART_NORM(flat_num) LIKE ?
                   OR SMART_NORM(printed_number) LIKE ?
                   OR SMART_NORM(hex_value) LIKE ?
                ORDER BY id DESC
                LIMIT 50
                """,
                [normalized_pattern] * 5,
            )
        ]

        employee_rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT
                    e.*,
                    COUNT(CASE WHEN ek.status = 'active' THEN 1 END) AS key_count,
                    GROUP_CONCAT(
                        CASE WHEN ek.status = 'active' THEN k.number END,
                        ' '
                    ) AS key_numbers
                FROM employees e
                LEFT JOIN employee_keys ek ON ek.employee_id = e.id
                LEFT JOIN keys k ON k.id = ek.key_id
                GROUP BY e.id
                ORDER BY e.enabled DESC, e.full_name COLLATE NOCASE
                LIMIT 800
                """
            )
        ]
        result["employee_results"] = _rank_records(
            query,
            employee_rows,
            (
                "full_name",
                "position",
                "department",
                "phone",
                "email",
                "key_numbers",
                "note",
            ),
            limit=20,
        )

        panel_rows = [
            normalize_panel_row(row)
            for row in conn.execute(
                """
                SELECT *
                FROM panels
                ORDER BY enabled DESC, address COLLATE NOCASE, entrance COLLATE NOCASE
                LIMIT 1500
                """
            )
        ]
        result["panel_results"] = _rank_records(
            query,
            panel_rows,
            (
                "id",
                "address",
                "entrance",
                "name",
                "mac",
                "ip",
                "device_model",
            ),
            limit=20,
        )

        uk_rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT
                    g.*,
                    COUNT(DISTINCT gp.panel_id) AS panel_count,
                    COUNT(DISTINCT gk.key_id) AS key_count
                FROM uk_groups g
                LEFT JOIN uk_group_panels gp ON gp.group_id = g.id
                LEFT JOIN uk_group_keys gk ON gk.group_id = g.id
                GROUP BY g.id
                ORDER BY g.name COLLATE NOCASE
                LIMIT 500
                """
            )
        ]
        result["uk_results"] = _rank_records(
            query,
            uk_rows,
            (
                "name",
                "legal_name",
                "note",
                "contact_name",
                "phone",
                "email",
                "legal_address",
                "contract_number",
                "account_manager",
                "cooperation_note",
            ),
            limit=20,
        )

        operation_rows = [
            normalize_operation_row(dict(row))
            for row in conn.execute(
                """
                SELECT *
                FROM operation_log
                ORDER BY id DESC
                LIMIT 800
                """
            )
        ]
        result["operation_results"] = _rank_records(
            query,
            operation_rows,
            (
                "action",
                "object_name",
                "details",
                "printed_number",
                "hex_value",
                "address",
                "apartment",
                "panel_name",
                "user_full_name",
            ),
            limit=30,
        )

    result["result_counts"] = {
        "keys": len(result["inventory_results"]),
        "employees": len(result["employee_results"]),
        "panels": len(result["panel_results"]),
        "uk": len(result["uk_results"]),
        "operations": len(result["operation_results"]),
    }

    return result


def _rank_records(
    query: str,
    rows: list[dict],
    fields: tuple[str, ...],
    *,
    limit: int,
) -> list[dict]:
    ranked: list[tuple[float, dict]] = []
    for row in rows:
        values = [str(row.get(field) or "") for field in fields]
        if not matches_search(query, *values, threshold=0.53):
            continue
        score = max((search_score(query, value) for value in values), default=0)
        ranked.append((score, row))
    ranked.sort(key=lambda item: -item[0])
    return [row for _, row in ranked[:limit]]
