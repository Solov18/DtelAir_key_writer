import re
import unicodedata

from app.db import db
from app.repositories.log_repository import normalize_operation_row
from app.repositories.key_repository import get_key, get_keys_page
from app.repositories.panel_repository import normalize_panel_row
from app.search_utils import (
    matches_search,
    normalize_search_text,
    rank_search_candidates,
    search_score,
)
from app.services.keys import find_keys
from app.key_numbers import key_number_search_sql


_APARTMENT_QUERY_RE = re.compile(
    r"(?<![\w])кв(?:артира)?\.?\s*(?:№|#)?\s*"
    r"(?P<apartment>\d+[а-яa-z]?(?:/\d+)?)\b",
    re.IGNORECASE,
)
_ADDRESS_NOISE_RE = re.compile(
    r"\b(?:улица|ул|дом|д|город|г|адрес|россия|сочи|адлер)\b\.?",
    re.IGNORECASE,
)


_TECHNICAL_IDENTIFIER_RE = re.compile(
    r"^(?:"
    r"[0-9A-Fa-f]{6,16}"
    r"|(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}"
    r"|(?:\d{1,3}\.){3}\d{1,3}"
    r")$"
)


def _is_technical_identifier_query(query: str) -> bool:
    """Return True for a key HEX, MAC, IP or another long identifier.

    Fuzzy similarity is useful for names and addresses, but it creates false
    positives for identifiers (for example, a key HEX can look similar to an
    IP address).  Such values must only match as normalized substrings.
    """

    compact = re.sub(r"\s+", "", str(query or "").strip())
    return bool(_TECHNICAL_IDENTIFIER_RE.fullmatch(compact))


def _contains_normalized_query(query: str, *values) -> bool:
    normalized_query = normalize_search_text(query)
    return bool(normalized_query) and any(
        normalized_query in normalize_search_text(value)
        for value in values
        if value not in (None, "")
    )


def _canonical_apartment(value: object) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    normalized = re.sub(r"[\s._-]+", "", normalized)
    match = re.fullmatch(r"0*(\d+)([а-яa-z]?)(?:/0*(\d+))?", normalized)
    if not match:
        return normalized
    main = str(int(match.group(1) or "0"))
    suffix = match.group(2) or ""
    fraction = match.group(3)
    return f"{main}{suffix}{f'/{int(fraction)}' if fraction else ''}"


def _canonical_address(value: object) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    normalized = normalized.replace("ё", "е")
    normalized = re.sub(r"\\+", "/", normalized)
    normalized = re.sub(r"/\s+|\s+/", "/", normalized)
    normalized = re.sub(r"[_.,;:()\[\]{}№#'\"«»–—-]+", " ", normalized)
    normalized = _ADDRESS_NOISE_RE.sub(" ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _parse_location_query(query: str) -> dict:
    apartment_match = _APARTMENT_QUERY_RE.search(query or "")
    apartment = (
        _canonical_apartment(apartment_match.group("apartment"))
        if apartment_match
        else ""
    )
    address_source = query or ""
    if apartment_match:
        address_source = (
            address_source[: apartment_match.start()]
            + " "
            + address_source[apartment_match.end() :]
        )
    address_source = re.sub(r"\s+", " ", address_source).strip(" ,.;")
    address = _canonical_address(address_source)
    looks_like_address = bool(
        address
        and re.search(r"[а-яa-z]", address, re.IGNORECASE)
        and re.search(r"\d", address)
    )
    return {
        "apartment": apartment,
        "address_source": address_source,
        "address": address,
        "has_apartment": bool(apartment_match),
        "looks_like_address": looks_like_address,
    }


def _address_sql_terms(canonical_address: str) -> list[str]:
    tokens = canonical_address.split()
    street_tokens = [token for token in tokens if re.search(r"[а-яa-z]", token, re.I)]
    house_tokens = [token for token in tokens if re.search(r"\d", token)]
    terms: list[str] = []
    if street_tokens:
        terms.append(max(street_tokens, key=len))
    if house_tokens:
        terms.append(house_tokens[-1])
    return terms


def _set_result_counts(result: dict) -> dict:
    result["result_counts"] = {
        "keys": len(result["inventory_results"]),
        "employees": len(result["employee_results"]),
        "panels": len(result["panel_results"]),
        "uk": len(result["uk_results"]),
        "operations": len(result["operation_results"]),
    }
    return result


def _search_exact_location(result: dict, parsed: dict) -> dict | None:
    """Search address/apartment fields without matching technical identifiers."""
    requested_address = parsed["address"]
    requested_apartment = parsed["apartment"]

    with db() as conn:
        panel_rows = [
            normalize_panel_row(row)
            for row in conn.execute(
                """
                SELECT *
                FROM panels
                ORDER BY enabled DESC, LOWER(address), address, id
                """
            )
        ]
        exact_house_panels = [
            row
            for row in panel_rows
            if requested_address
            and _canonical_address(row.get("address")) == requested_address
        ]

        if not parsed["has_apartment"]:
            if not parsed["looks_like_address"] or not exact_house_panels:
                return None
            assignment_rows = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT key_id, address, apartment
                    FROM key_assignments
                    WHERE active = 1
                    """
                )
                if _canonical_address(row["address"]) == requested_address
            ]
        else:
            assignment_rows = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT key_id, address, apartment
                    FROM key_assignments
                    WHERE active = 1
                      AND LOWER(BTRIM(COALESCE(apartment, ''))) = ?
                    """,
                    (requested_apartment,),
                )
                if _canonical_apartment(row["apartment"]) == requested_apartment
                and (
                    not requested_address
                    or _canonical_address(row["address"]) == requested_address
                )
            ]

        assignment_key_ids = sorted(
            {
                int(row["key_id"])
                for row in assignment_rows
                if row.get("key_id") is not None
            }
        )
        operation_conditions: list[str] = []
        operation_params: list[object] = []
        location_conditions: list[str] = []
        location_params: list[object] = []
        if parsed["has_apartment"]:
            location_conditions.append(
                "(LOWER(BTRIM(COALESCE(apartment, ''))) = ? "
                "OR LOWER(BTRIM(COALESCE(flat_num, ''))) = ?)"
            )
            location_params.extend((requested_apartment, requested_apartment))
        if requested_address:
            for address_term in _address_sql_terms(requested_address):
                location_conditions.append("LOWER(COALESCE(address, '')) LIKE ?")
                location_params.append(f"%{address_term}%")
        if location_conditions:
            operation_conditions.append(f"({' AND '.join(location_conditions)})")
            operation_params.extend(location_params)
        if assignment_key_ids:
            placeholders = ", ".join("?" for _ in assignment_key_ids)
            operation_conditions.append(f"key_id IN ({placeholders})")
            operation_params.extend(assignment_key_ids)

        operation_candidates = [
            normalize_operation_row(dict(row))
            for row in conn.execute(
                f"""
                SELECT *
                FROM operation_log
                WHERE {' OR '.join(operation_conditions) if operation_conditions else 'FALSE'}
                ORDER BY id DESC
                LIMIT 5000
                """,
                operation_params,
            )
        ]
        exact_location_operations = [
            row
            for row in operation_candidates
            if (
                not parsed["has_apartment"]
                or _canonical_apartment(row.get("apartment") or row.get("flat_num"))
                == requested_apartment
            )
            and (
                not requested_address
                or _canonical_address(row.get("address")) == requested_address
            )
        ]

    key_ids = {
        int(row["key_id"])
        for row in assignment_rows
        if row.get("key_id") is not None
    }
    key_ids.update(
        int(row["key_id"])
        for row in exact_location_operations
        if row.get("key_id") is not None
    )
    inventory_results = [get_key(key_id) for key_id in sorted(key_ids, reverse=True)]
    result["inventory_results"] = [item for item in inventory_results if item]
    result["key"] = (
        result["inventory_results"][0]
        if len(result["inventory_results"]) == 1
        else None
    )

    linked_addresses = {
        _canonical_address(row.get("address"))
        for row in [*assignment_rows, *exact_location_operations]
        if _canonical_address(row.get("address"))
    }
    apartment_found = bool(assignment_rows or exact_location_operations)
    if parsed["has_apartment"]:
        result["panel_results"] = [
            row
            for row in panel_rows
            if apartment_found
            and _canonical_address(row.get("address")) in linked_addresses
        ][:20]
    else:
        result["panel_results"] = exact_house_panels[:20]

    operation_results = []
    for row in operation_candidates:
        matches_key = row.get("key_id") is not None and int(row["key_id"]) in key_ids
        matches_location = (
            (not requested_address or _canonical_address(row.get("address")) == requested_address)
            and (
                not parsed["has_apartment"]
                or _canonical_apartment(row.get("apartment") or row.get("flat_num"))
                == requested_apartment
            )
        )
        if matches_key or matches_location:
            operation_results.append(row)
        if len(operation_results) >= 50:
            break
    result["operation_results"] = operation_results
    result["address_results"] = operation_results
    result["history"] = operation_results if result["key"] else []
    result["last_operation"] = result["history"][0] if result["history"] else None

    house_found = bool(exact_house_panels) or any(
        _canonical_address(row.get("address")) == requested_address
        for row in assignment_rows
    )
    result["structured_query"] = {
        **parsed,
        "house_found": house_found,
        "apartment_found": apartment_found,
        "matched_address": (
            exact_house_panels[0].get("address")
            if exact_house_panels
            else next(
                (row.get("address") for row in assignment_rows if row.get("address")),
                parsed["address_source"],
            )
        ),
    }
    if parsed["has_apartment"] and not apartment_found:
        if parsed["address_source"]:
            result["no_results_message"] = (
                f"По адресу {parsed['address_source']} квартира "
                f"{requested_apartment} ничего не найдено"
            )
        else:
            result["no_results_message"] = (
                f"По квартире {requested_apartment} ничего не найдено"
            )
    return _set_result_counts(result)


def get_search_suggestions(
    query: str,
    scope: str = "universal",
    limit: int = 8,
    *,
    include_uk_credentials: bool = True,
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
                    STRING_AGG(
                        k.number,
                        ' ' ORDER BY ek.issued_at DESC, ek.id DESC
                    ) AS key_numbers
                FROM employees e
                LEFT JOIN employee_keys ek
                    ON ek.employee_id = e.id AND ek.status = 'active'
                LEFT JOIN keys k ON k.id = ek.key_id
                WHERE e.enabled = 1
                GROUP BY e.id
                ORDER BY LOWER(e.full_name), e.full_name
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
                ORDER BY
                    LOWER(address),
                    address,
                    LOWER(COALESCE(entrance, '')),
                    COALESCE(entrance, '')
                LIMIT 1000
                """
            ).fetchall()
            panel_groups: dict[str, dict] = {}
            for row in panel_rows:
                value = str(row["address"] or row["name"] or "").strip()
                group_key = normalize_search_text(value)
                if not group_key:
                    continue
                group = panel_groups.setdefault(
                    group_key,
                    {
                        "value": value,
                        "label": value,
                        "entrances": [],
                        "search_parts": [],
                        "count": 0,
                    },
                )
                group["count"] += 1
                entrance = str(row["entrance"] or "").strip()
                if entrance and entrance not in group["entrances"]:
                    group["entrances"].append(entrance)
                group["search_parts"].extend(
                    str(row[field] or "")
                    for field in ("id", "address", "entrance", "name", "mac", "ip")
                )

            for group in panel_groups.values():
                count = int(group["count"])
                entrances = ", ".join(group["entrances"][:4])
                if len(group["entrances"]) > 4:
                    entrances += f" и ещё {len(group['entrances']) - 4}"
                panel_word = "панель" if count == 1 else "панели" if 2 <= count <= 4 else "панелей"
                meta = f"{count} {panel_word}"
                if entrances:
                    meta += f" · {entrances}"
                candidates.append(
                    {
                        "value": group["value"],
                        "label": group["label"],
                        "meta": meta,
                        "search_text": " ".join(group["search_parts"]),
                    }
                )

        if scope in {"universal", "keys"}:
            key_number_sql, key_number_params = key_number_search_sql(
                "k.number", query, pattern=pattern
            )
            key_rows = conn.execute(
                f"""
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
                    {key_number_sql}
                    OR SMART_NORM(k.hex_value) LIKE ?
                    OR SMART_NORM(kt.name) LIKE ?
                    OR SMART_NORM(e.full_name) LIKE ?
                    OR SMART_NORM(ka.address) LIKE ?
                    OR SMART_NORM(ka.apartment) LIKE ?
                  )
                ORDER BY k.id DESC
                LIMIT 100
                """,
                [*key_number_params, *([pattern] * 5)],
            ).fetchall()
            candidates.extend(
                {
                    # A suggestion selected by HEX must keep searching by the
                    # same unambiguous identifier.  Using the printed number
                    # here used to turn e.g. F0291360 into the broad query 20.
                    "value": row["hex_value"],
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
            uk_credential_select = ", g.crm_login" if include_uk_credentials else ""
            uk_credential_condition = (
                " OR SMART_NORM(g.crm_login) LIKE ?"
                if include_uk_credentials
                else ""
            )
            uk_search_fields = (
                "name",
                "legal_name",
                "note",
                "contact_name",
                "phone",
                "email",
                "legal_address",
                "actual_address",
            ) + (("crm_login",) if include_uk_credentials else ())
            uk_rows = conn.execute(
                f"""
                SELECT
                    g.id,
                    g.name,
                    g.legal_name,
                    g.note,
                    g.contact_name,
                    g.phone,
                    g.email,
                    g.legal_address,
                    g.actual_address
                    {uk_credential_select}
                FROM uk_groups g
                WHERE g.archived_at IS NULL
                  AND (
                    SMART_NORM(g.name) LIKE ?
                    OR SMART_NORM(g.legal_name) LIKE ?
                    OR SMART_NORM(g.note) LIKE ?
                    OR SMART_NORM(g.contact_name) LIKE ?
                    OR SMART_NORM(g.phone) LIKE ?
                    OR SMART_NORM(g.email) LIKE ?
                    OR SMART_NORM(g.legal_address) LIKE ?
                    OR SMART_NORM(g.actual_address) LIKE ?
                    {uk_credential_condition}
                  )
                ORDER BY LOWER(g.name), g.name
                LIMIT 80
                """,
                [pattern] * len(uk_search_fields),
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
                            row["actual_address"] or row["legal_address"],
                        )
                        if value
                    ) or "Управляющая компания",
                    "search_text": " ".join(
                        str(row[field] or "")
                        for field in uk_search_fields
                    ),
                }
                for row in uk_rows
            )

        if scope in {"universal", "log"}:
            log_number_sql, log_number_params = key_number_search_sql(
                "printed_number", query, pattern=pattern
            )
            log_rows = conn.execute(
                f"""
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
                    OR {log_number_sql}
                    OR SMART_NORM(address) LIKE ?
                ORDER BY id DESC
                LIMIT 100
                """,
                [*([pattern] * 4), *log_number_params, pattern],
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

    if _is_technical_identifier_query(query):
        candidates = [
            item
            for item in candidates
            if _contains_normalized_query(
                query,
                item.get("value"),
                item.get("label"),
                item.get("search_text"),
            )
        ]

    # When a panel address has a direct normalized match, do not mix it with
    # weak fuzzy suggestions from unrelated streets.  Fuzzy candidates remain
    # available for misspelled queries where no direct match exists.
    if scope == "panels":
        direct_panel_candidates = [
            item
            for item in candidates
            if _contains_normalized_query(
                query,
                item.get("value"),
                item.get("label"),
                item.get("search_text"),
            )
        ]
        if direct_panel_candidates:
            candidates = direct_panel_candidates

    return rank_search_candidates(query, candidates, limit=limit)


def universal_search(query: str, *, include_uk_credentials: bool = True):
    query = (query or "").strip()
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

    parsed_location = _parse_location_query(query)
    if parsed_location["has_apartment"] or parsed_location["looks_like_address"]:
        location_result = _search_exact_location(result, parsed_location)
        if location_result is not None:
            return location_result

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
        log_number_sql, log_number_params = key_number_search_sql(
            "printed_number", query, pattern=normalized_pattern
        )
        result["address_results"] = [
            normalize_operation_row(dict(row))
            for row in conn.execute(
                f"""
                SELECT *
                FROM operation_log
                WHERE SMART_NORM(address) LIKE ?
                   OR SMART_NORM(apartment) LIKE ?
                   OR SMART_NORM(flat_num) LIKE ?
                   OR {log_number_sql}
                   OR SMART_NORM(hex_value) LIKE ?
                ORDER BY id DESC
                LIMIT 50
                """,
                [normalized_pattern, normalized_pattern, normalized_pattern,
                 *log_number_params, normalized_pattern],
            )
        ]

        employee_rows = [
            dict(row)
            for row in conn.execute(
                f"""
                SELECT
                    e.*,
                    COUNT(CASE WHEN ek.status = 'active' THEN 1 END) AS key_count,
                    STRING_AGG(
                        CASE WHEN ek.status = 'active' THEN k.number END,
                        ' ' ORDER BY ek.issued_at DESC, ek.id DESC
                    ) AS key_numbers
                FROM employees e
                LEFT JOIN employee_keys ek ON ek.employee_id = e.id
                LEFT JOIN keys k ON k.id = ek.key_id
                GROUP BY e.id
                ORDER BY e.enabled DESC, LOWER(e.full_name), e.full_name
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
                ORDER BY
                    enabled DESC,
                    LOWER(address),
                    address,
                    LOWER(COALESCE(entrance, '')),
                    COALESCE(entrance, '')
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

        uk_credential_select = ", g.crm_login" if include_uk_credentials else ""
        uk_search_fields = (
            "name",
            "legal_name",
            "note",
            "contact_name",
            "phone",
            "email",
            "legal_address",
            "actual_address",
        ) + (("crm_login",) if include_uk_credentials else ())
        uk_rows = [
            dict(row)
            for row in conn.execute(
                f"""
                SELECT
                    g.id,
                    g.name,
                    g.legal_name,
                    g.note,
                    g.contact_name,
                    g.phone,
                    g.email,
                    g.legal_address,
                    g.actual_address
                    {uk_credential_select},
                    COUNT(DISTINCT pl.panel_id)
                        FILTER (WHERE pl.active IS TRUE) AS panel_count,
                    COUNT(DISTINCT ki.key_id)
                        FILTER (WHERE ki.status IN ('pending', 'active'))
                        AS key_count
                FROM uk_groups g
                LEFT JOIN uk_panel_links pl ON pl.uk_group_id = g.id
                LEFT JOIN uk_key_issues ki ON ki.uk_group_id = g.id
                WHERE g.archived_at IS NULL
                GROUP BY g.id
                ORDER BY LOWER(g.name), g.name
                LIMIT 500
                """
            )
        ]
        result["uk_results"] = _rank_records(
            query,
            uk_rows,
            uk_search_fields,
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

    return _set_result_counts(result)


def _rank_records(
    query: str,
    rows: list[dict],
    fields: tuple[str, ...],
    *,
    limit: int,
) -> list[dict]:
    ranked: list[tuple[float, dict]] = []
    strict_identifier = _is_technical_identifier_query(query)
    for row in rows:
        values = [str(row.get(field) or "") for field in fields]
        if strict_identifier:
            if not _contains_normalized_query(query, *values):
                continue
        elif not matches_search(query, *values, threshold=0.53):
            continue
        score = max((search_score(query, value) for value in values), default=0)
        ranked.append((score, row))
    ranked.sort(key=lambda item: -item[0])
    return [row for _, row in ranked[:limit]]
