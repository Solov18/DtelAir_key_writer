import math
import re

from sqlalchemy.exc import IntegrityError

from app.db import db
from app.repositories.key_repository import (
    release_key_on_connection,
    set_key_assignment_on_connection,
)
from app.search_utils import normalize_search_text


ACTIVE_ISSUE_STATUSES = ("pending", "active")


def _clean(value: str | None) -> str:
    return (value or "").strip()


def get_group_statistics() -> dict:
    with db() as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE archived_at IS NULL) AS total,
                (
                    SELECT COUNT(*)
                    FROM uk_panel_links
                    WHERE active IS TRUE
                ) AS panels,
                (
                    SELECT COUNT(*)
                    FROM uk_key_issues
                    WHERE status IN ('pending', 'active')
                ) AS keys,
                (
                    SELECT COUNT(*)
                    FROM (
                        SELECT kp.issue_id
                        FROM uk_key_programmings kp
                        JOIN uk_key_issues ki ON ki.id = kp.issue_id
                        WHERE kp.active IS TRUE
                          AND ki.status IN ('pending', 'active')
                        GROUP BY kp.issue_id
                        HAVING COUNT(*) > 1
                    ) master_keys
                ) AS master_keys
            FROM uk_groups
            """
        ).fetchone()
    return dict(row)


def get_group_page(
    query: str = "",
    page: int = 1,
    page_size: int = 20,
    include_archived: bool = False,
) -> dict:
    page = max(1, int(page))
    page_size = max(1, min(100, int(page_size)))
    normalized_query = normalize_search_text(query)
    params: list[object] = []
    conditions = ["1 = 1" if include_archived else "g.archived_at IS NULL"]

    if normalized_query:
        pattern = f"%{normalized_query}%"
        conditions.append(
            """
            (
                SMART_NORM(g.name) LIKE ?
                OR SMART_NORM(g.legal_name) LIKE ?
                OR SMART_NORM(g.contact_name) LIKE ?
                OR SMART_NORM(g.phone) LIKE ?
                OR SMART_NORM(g.email) LIKE ?
                OR SMART_NORM(g.legal_address) LIKE ?
                OR SMART_NORM(g.actual_address) LIKE ?
                OR SMART_NORM(g.crm_login) LIKE ?
                OR SMART_NORM(g.note) LIKE ?
            )
            """
        )
        params.extend([pattern] * 9)

    where_sql = " AND ".join(conditions)
    with db() as conn:
        total = int(
            conn.execute(
                f"SELECT COUNT(*) FROM uk_groups g WHERE {where_sql}",
                params,
            ).fetchone()[0]
        )
        pages = max(1, math.ceil(total / page_size))
        page = min(page, pages)
        offset = (page - 1) * page_size
        rows = conn.execute(
            f"""
            SELECT
                g.id,
                g.name,
                g.legal_name,
                g.contact_name,
                g.phone,
                g.email,
                g.legal_address,
                g.actual_address,
                g.note,
                g.created_by,
                g.created_at,
                g.updated_at,
                g.archived_at,
                (
                    SELECT COUNT(*)
                    FROM uk_panel_links pl
                    WHERE pl.uk_group_id = g.id AND pl.active IS TRUE
                ) AS panels_count,
                (
                    SELECT COUNT(*)
                    FROM uk_key_issues ki
                    WHERE ki.uk_group_id = g.id
                      AND ki.status IN ('pending', 'active')
                ) AS keys_count,
                (
                    SELECT COUNT(*)
                    FROM (
                        SELECT kp.issue_id
                        FROM uk_key_programmings kp
                        JOIN uk_key_issues ki ON ki.id = kp.issue_id
                        WHERE ki.uk_group_id = g.id
                          AND ki.status IN ('pending', 'active')
                          AND kp.active IS TRUE
                        GROUP BY kp.issue_id
                        HAVING COUNT(*) > 1
                    ) grouped
                ) AS master_keys_count
            FROM uk_groups g
            WHERE {where_sql}
            ORDER BY LOWER(g.name), g.name, g.id
            LIMIT ? OFFSET ?
            """,
            [*params, page_size, offset],
        ).fetchall()

    return {
        "items": [dict(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
    }


def get_groups() -> list[dict]:
    return get_group_page(page_size=100)["items"]


def get_group(group_id: int, *, include_archived: bool = False) -> dict | None:
    archived_filter = "" if include_archived else "AND g.archived_at IS NULL"
    with db() as conn:
        row = conn.execute(
            f"""
            SELECT
                g.id,
                g.name,
                g.legal_name,
                g.contact_name,
                g.phone,
                g.email,
                g.legal_address,
                g.actual_address,
                g.note,
                g.created_by,
                g.created_at,
                g.updated_at,
                g.archived_at,
                CASE WHEN BTRIM(g.crm_login) <> '' THEN TRUE ELSE FALSE END
                    AS crm_login_configured,
                CASE WHEN BTRIM(g.crm_password) <> '' THEN TRUE ELSE FALSE END
                    AS crm_password_configured,
                (
                    SELECT COUNT(*) FROM uk_panel_links pl
                    WHERE pl.uk_group_id = g.id AND pl.active IS TRUE
                ) AS panels_count,
                (
                    SELECT COUNT(*) FROM uk_key_issues ki
                    WHERE ki.uk_group_id = g.id
                      AND ki.status IN ('pending', 'active')
                ) AS keys_count,
                (
                    SELECT COUNT(*)
                    FROM (
                        SELECT kp.issue_id
                        FROM uk_key_programmings kp
                        JOIN uk_key_issues ki ON ki.id = kp.issue_id
                        WHERE ki.uk_group_id = g.id
                          AND ki.status IN ('pending', 'active')
                          AND kp.active IS TRUE
                        GROUP BY kp.issue_id
                        HAVING COUNT(*) > 1
                    ) grouped
                ) AS master_keys_count
            FROM uk_groups g
            WHERE g.id = ? {archived_filter}
            """,
            (group_id,),
        ).fetchone()
    return dict(row) if row else None


def get_group_credentials(group_id: int) -> dict | None:
    """Return secrets only to an explicitly authorised caller."""

    with db() as conn:
        row = conn.execute(
            """
            SELECT id, crm_login, crm_password
            FROM uk_groups
            WHERE id = ? AND archived_at IS NULL
            """,
            (group_id,),
        ).fetchone()
    return dict(row) if row else None


def save_group(
    name: str,
    note: str = "",
    crm_login: str = "",
    crm_password: str = "",
    legal_name: str = "",
    contact_name: str = "",
    phone: str = "",
    email: str = "",
    legal_address: str = "",
    actual_address: str = "",
    created_by: str = "",
) -> int:
    clean_name = _clean(name)
    if not clean_name:
        raise ValueError("Краткое название УК обязательно.")

    try:
        with db() as conn:
            cursor = conn.execute(
                """
                INSERT INTO uk_groups(
                    name, legal_name, contact_name, phone, email,
                    legal_address, actual_address, crm_login, crm_password,
                    note, created_by
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    clean_name,
                    _clean(legal_name),
                    _clean(contact_name),
                    _clean(phone),
                    _clean(email),
                    _clean(legal_address),
                    _clean(actual_address),
                    _clean(crm_login),
                    crm_password or "",
                    _clean(note),
                    _clean(created_by),
                ),
            )
            return int(cursor.lastrowid)
    except IntegrityError as error:
        raise ValueError("УК с таким кратким названием уже существует.") from error


def update_group(
    group_id: int,
    name: str,
    note: str = "",
    legal_name: str = "",
    contact_name: str = "",
    phone: str = "",
    email: str = "",
    legal_address: str = "",
    actual_address: str = "",
    crm_login: str | None = None,
    crm_password: str | None = None,
    allow_credentials: bool = False,
) -> None:
    clean_name = _clean(name)
    if not clean_name:
        raise ValueError("Краткое название УК обязательно.")

    values: list[object] = [
        clean_name,
        _clean(legal_name),
        _clean(contact_name),
        _clean(phone),
        _clean(email),
        _clean(legal_address),
        _clean(actual_address),
        _clean(note),
    ]
    credential_sql = ""
    if allow_credentials:
        credential_sql = ", crm_login = ?"
        values.append(_clean(crm_login))
        if crm_password:
            credential_sql += ", crm_password = ?"
            values.append(crm_password)
    values.append(group_id)

    try:
        with db() as conn:
            cursor = conn.execute(
                f"""
                UPDATE uk_groups
                SET name = ?,
                    legal_name = ?,
                    contact_name = ?,
                    phone = ?,
                    email = ?,
                    legal_address = ?,
                    actual_address = ?,
                    note = ?,
                    updated_at = CURRENT_TIMESTAMP
                    {credential_sql}
                WHERE id = ? AND archived_at IS NULL
                """,
                values,
            )
            if cursor.rowcount == 0:
                raise ValueError("Управляющая компания не найдена.")
    except IntegrityError as error:
        raise ValueError("УК с таким кратким названием уже существует.") from error


def archive_group(group_id: int) -> None:
    with db() as conn:
        cursor = conn.execute(
            """
            UPDATE uk_groups
            SET archived_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP,
                crm_login = '',
                crm_password = ''
            WHERE id = ? AND archived_at IS NULL
            """,
            (group_id,),
        )
        if cursor.rowcount == 0:
            raise ValueError("Управляющая компания не найдена.")
        # The relationship remains as history, but an archived company is no
        # longer an active owner and must not reserve its panels forever.
        conn.execute(
            """
            UPDATE uk_panel_links
            SET active = FALSE,
                detached_at = COALESCE(detached_at, CURRENT_TIMESTAMP),
                updated_at = CURRENT_TIMESTAMP
            WHERE uk_group_id = ? AND active IS TRUE
            """,
            (group_id,),
        )


def delete_group(group_id: int) -> None:
    """Compatibility name: deleting a company is deliberately an archive."""

    archive_group(group_id)


def get_group_panels(group_id: int, *, include_detached: bool = False) -> list[dict]:
    active_filter = "" if include_detached else "AND pl.active IS TRUE"
    with db() as conn:
        return [
            dict(row)
            for row in conn.execute(
                f"""
                SELECT
                    pl.id AS link_id,
                    pl.uk_group_id,
                    pl.panel_id,
                    pl.apartment,
                    pl.comment AS link_comment,
                    pl.active AS link_active,
                    pl.created_at AS linked_at,
                    pl.detached_at,
                    p.*
                FROM uk_panel_links pl
                JOIN panels p ON p.id = pl.panel_id
                WHERE pl.uk_group_id = ? {active_filter}
                ORDER BY LOWER(p.address), LOWER(p.entrance), LOWER(p.name), p.id
                """,
                (group_id,),
            )
        ]


def get_available_panels(group_id: int) -> list[dict]:
    with db() as conn:
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT p.*
                FROM panels p
                WHERE p.enabled = 1
                  AND NOT EXISTS (
                      SELECT 1
                      FROM uk_panel_links pl
                      WHERE pl.panel_id = p.id AND pl.active IS TRUE
                  )
                ORDER BY LOWER(p.address), LOWER(p.entrance), LOWER(p.name), p.id
                """
            )
        ]


def add_panel(
    group_id: int,
    panel_id: int,
    apartment: str,
    comment: str = "",
    created_by: str = "",
) -> int:
    clean_apartment = _clean(apartment)
    if not clean_apartment:
        raise ValueError("Укажите квартиру учётной записи УК для этой панели.")

    try:
        with db() as conn:
            if not conn.execute(
                "SELECT 1 FROM uk_groups WHERE id = ? AND archived_at IS NULL",
                (group_id,),
            ).fetchone():
                raise ValueError("Управляющая компания не найдена.")
            if not conn.execute(
                "SELECT 1 FROM panels WHERE id = ? AND enabled = 1",
                (panel_id,),
            ).fetchone():
                raise ValueError("Панель не найдена или отключена.")

            old_link = conn.execute(
                """
                SELECT id
                FROM uk_panel_links
                WHERE uk_group_id = ? AND panel_id = ? AND active IS FALSE
                ORDER BY id DESC
                LIMIT 1
                """,
                (group_id, panel_id),
            ).fetchone()
            if old_link:
                conn.execute(
                    """
                    UPDATE uk_panel_links
                    SET apartment = ?, comment = ?, active = TRUE,
                        created_by = ?, detached_at = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        clean_apartment,
                        _clean(comment),
                        _clean(created_by),
                        old_link["id"],
                    ),
                )
                return int(old_link["id"])

            cursor = conn.execute(
                """
                INSERT INTO uk_panel_links(
                    uk_group_id, panel_id, apartment, comment, created_by
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    group_id,
                    panel_id,
                    clean_apartment,
                    _clean(comment),
                    _clean(created_by),
                ),
            )
            return int(cursor.lastrowid)
    except IntegrityError as error:
        raise ValueError("Эта панель уже закреплена за управляющей компанией.") from error


def update_panel_link(
    group_id: int,
    link_id: int,
    apartment: str,
    comment: str = "",
) -> None:
    clean_apartment = _clean(apartment)
    if not clean_apartment:
        raise ValueError("Номер квартиры не может быть пустым.")
    with db() as conn:
        cursor = conn.execute(
            """
            UPDATE uk_panel_links
            SET apartment = ?, comment = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND uk_group_id = ? AND active IS TRUE
            """,
            (clean_apartment, _clean(comment), link_id, group_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("Связь УК и панели не найдена.")


def remove_panel(group_id: int, panel_id: int | None = None, link_id: int | None = None) -> None:
    if link_id is None and panel_id is None:
        raise ValueError("Не указана связь с панелью.")
    condition = "pl.id = ?" if link_id is not None else "pl.panel_id = ?"
    value = link_id if link_id is not None else panel_id

    with db() as conn:
        link = conn.execute(
            f"""
            SELECT pl.id
            FROM uk_panel_links pl
            WHERE pl.uk_group_id = ? AND {condition} AND pl.active IS TRUE
            """,
            (group_id, value),
        ).fetchone()
        if not link:
            raise ValueError("Связь УК и панели не найдена.")
        if conn.execute(
            """
            SELECT 1
            FROM uk_key_programmings
            WHERE panel_link_id = ? AND active IS TRUE
            LIMIT 1
            """,
            (link["id"],),
        ).fetchone():
            raise ValueError(
                "Сначала удалите или отвяжите ключи УК от этой панели."
            )
        conn.execute(
            """
            UPDATE uk_panel_links
            SET active = FALSE, detached_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (link["id"],),
        )


def add_panels(group_id: int, panel_ids: list[int]) -> None:
    """Legacy helper retained only for callers that provide no apartment."""

    if panel_ids:
        raise ValueError("Для каждой панели необходимо указать отдельную квартиру.")


def get_available_keys(
    query: str = "",
    limit: int = 100,
    *,
    key_type_id: int | None = None,
) -> list[dict]:
    normalized = normalize_search_text(query)
    raw_query = _clean(query)
    compact_query = re.sub(r"[^0-9A-Za-zА-Яа-яЁё]+", "", raw_query).upper()
    numeric_query = compact_query if compact_query.isdigit() else ""
    numeric_unpadded = numeric_query.lstrip("0") or ("0" if numeric_query else "")
    filter_params: list[object] = []
    condition = ""
    if normalized:
        condition = "AND SMART_NORM(CONCAT_WS(' ', kt.name, k.number, k.hex_value)) LIKE ?"
        filter_params.append(f"%{normalized}%")
    type_condition = ""
    if key_type_id is not None:
        type_condition = "AND kt.id = ?"
        filter_params.append(int(key_type_id))
    query_limit = max(1, min(int(limit), 200))

    with db() as conn:
        return [
            dict(row)
            for row in conn.execute(
                f"""
                WITH available AS (
                    SELECT k.id, k.number, k.hex_value, k.status,
                           kt.id AS type_id, kt.name AS type_name,
                           kt.color AS type_color,
                           CASE
                               WHEN UPPER(REGEXP_REPLACE(k.hex_value, '[^0-9A-Za-z]', '', 'g')) = ? THEN 0
                               WHEN ? <> '' AND COALESCE(NULLIF(LTRIM(k.number, '0'), ''), '0') = ? THEN 0
                               WHEN SMART_NORM(k.number) = ? THEN 1
                               WHEN SMART_NORM(kt.name) = ? THEN 2
                               ELSE 3
                           END AS search_rank
                    FROM keys k
                    JOIN key_types kt ON kt.id = k.key_type_id
                    WHERE BTRIM(k.hex_value) <> ''
                      AND k.status = 'free'
                      AND kt.enabled = 1
                      AND NOT EXISTS (
                          SELECT 1 FROM uk_key_issues ki
                          WHERE ki.key_id = k.id
                            AND ki.status IN ('pending', 'active')
                      )
                      {condition}
                      {type_condition}
                )
                SELECT id, number, hex_value, status,
                       type_id, type_name, type_color
                FROM available
                ORDER BY search_rank, LOWER(type_name),
                         LENGTH(number), LOWER(number), id
                LIMIT ?
                """,
                [compact_query, numeric_unpadded, numeric_unpadded, normalized, normalized]
                + filter_params
                + [query_limit],
            )
        ]


def search_group_panels(group_id: int, query: str = "", limit: int = 60) -> list[dict]:
    """Search every active panel linked to one UK; LIMIT is applied after matching."""

    normalized = normalize_search_text(query)
    params: list[object] = [group_id]
    condition = ""
    if normalized:
        condition = """
          AND SMART_NORM(CONCAT_WS(' ', p.address, p.entrance, p.name, p.mac, p.id)) LIKE ?
        """
        params.append(f"%{normalized}%")
    params.append(max(1, min(int(limit), 100)))
    with db() as conn:
        rows = conn.execute(
            f"""
            SELECT pl.id AS link_id, pl.panel_id, p.address, p.entrance,
                   p.name, p.mac, p.api_status AS status, p.enabled
            FROM uk_panel_links pl
            JOIN panels p ON p.id = pl.panel_id
            WHERE pl.uk_group_id = ? AND pl.active IS TRUE
              {condition}
            ORDER BY
              CASE WHEN SMART_NORM(p.address) = ? THEN 0 ELSE 1 END,
              LOWER(p.address), LOWER(COALESCE(p.entrance, '')),
              LOWER(COALESCE(p.name, '')), p.id
            LIMIT ?
            """,
            params[:-1] + [normalized, params[-1]],
        ).fetchall()
    return [dict(row) for row in rows]


def get_available_key_types() -> list[dict]:
    """Return database key types which currently have issuable keys."""

    with db() as conn:
        rows = conn.execute(
            """
            SELECT kt.id, kt.name, kt.color, COUNT(k.id) AS free_count
            FROM key_types kt
            JOIN keys k ON k.key_type_id = kt.id
            WHERE kt.enabled = 1
              AND k.status = 'free'
              AND BTRIM(k.hex_value) <> ''
              AND NOT EXISTS (
                  SELECT 1 FROM uk_key_issues ki
                  WHERE ki.key_id = k.id
                    AND ki.status IN ('pending', 'active')
              )
            GROUP BY kt.id, kt.name, kt.color
            ORDER BY LOWER(kt.name), kt.id
            """
        ).fetchall()
    return [dict(row) for row in rows]


def get_group_keys(group_id: int, *, include_closed: bool = False) -> list[dict]:
    status_filter = "" if include_closed else "AND ki.status IN ('pending', 'active')"
    with db() as conn:
        rows = conn.execute(
            f"""
            SELECT
                ki.id AS issue_id,
                ki.uk_group_id,
                ki.key_id,
                ki.status AS issue_status,
                ki.comment AS issue_comment,
                ki.issued_by,
                ki.issued_at,
                ki.released_at,
                k.number,
                k.hex_value,
                k.status AS key_status,
                kt.name AS type_name,
                kt.color AS type_color,
                COUNT(kp.id) FILTER (WHERE kp.active IS TRUE) AS panels_count
            FROM uk_key_issues ki
            JOIN keys k ON k.id = ki.key_id
            JOIN key_types kt ON kt.id = k.key_type_id
            LEFT JOIN uk_key_programmings kp ON kp.issue_id = ki.id
            WHERE ki.uk_group_id = ? {status_filter}
            GROUP BY ki.id, k.id, kt.id
            ORDER BY ki.issued_at DESC, ki.id DESC
            """,
            (group_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_issue(issue_id: int, *, group_id: int | None = None) -> dict | None:
    params: list[object] = [issue_id]
    group_filter = ""
    if group_id is not None:
        group_filter = "AND ki.uk_group_id = ?"
        params.append(group_id)
    with db() as conn:
        row = conn.execute(
            f"""
            SELECT
                ki.*,
                g.name AS uk_name,
                k.number,
                k.hex_value,
                k.status AS key_status,
                kt.name AS type_name,
                kt.color AS type_color
            FROM uk_key_issues ki
            JOIN uk_groups g ON g.id = ki.uk_group_id
            JOIN keys k ON k.id = ki.key_id
            JOIN key_types kt ON kt.id = k.key_type_id
            WHERE ki.id = ? {group_filter}
            """,
            params,
        ).fetchone()
    return dict(row) if row else None


def get_issue_programmings(issue_id: int, *, include_inactive: bool = True) -> list[dict]:
    active_filter = "" if include_inactive else "AND kp.active IS TRUE"
    with db() as conn:
        return [
            dict(row)
            for row in conn.execute(
                f"""
                SELECT
                    kp.*,
                    pl.uk_group_id,
                    pl.panel_id,
                    pl.apartment AS registered_apartment,
                    p.address,
                    p.entrance,
                    p.name AS panel_name,
                    p.mac,
                    (
                        SELECT co.safe_response
                        FROM uk_crm_operations co
                        WHERE co.programming_id = kp.id
                        ORDER BY co.started_at DESC, co.id DESC
                        LIMIT 1
                    ) AS crm_response,
                    (
                        SELECT co.status
                        FROM uk_crm_operations co
                        WHERE co.programming_id = kp.id
                        ORDER BY co.started_at DESC, co.id DESC
                        LIMIT 1
                    ) AS crm_status
                FROM uk_key_programmings kp
                JOIN uk_panel_links pl ON pl.id = kp.panel_link_id
                JOIN panels p ON p.id = pl.panel_id
                WHERE kp.issue_id = ? {active_filter}
                ORDER BY kp.active DESC, kp.is_primary DESC, kp.created_at, kp.id
                """,
                (issue_id,),
            )
        ]


def get_programming(programming_id: int) -> dict | None:
    with db() as conn:
        row = conn.execute(
            """
            SELECT
                kp.*,
                ki.uk_group_id,
                ki.key_id,
                ki.status AS issue_status,
                k.number,
                k.hex_value,
                pl.panel_id,
                pl.apartment AS registered_apartment,
                pl.active AS panel_link_active,
                p.address,
                p.entrance,
                p.name AS panel_name,
                p.mac
            FROM uk_key_programmings kp
            JOIN uk_key_issues ki ON ki.id = kp.issue_id
            JOIN keys k ON k.id = ki.key_id
            JOIN uk_panel_links pl ON pl.id = kp.panel_link_id
            JOIN panels p ON p.id = pl.panel_id
            WHERE kp.id = ?
            """,
            (programming_id,),
        ).fetchone()
    return dict(row) if row else None


def create_key_issue(
    group_id: int,
    key_id: int,
    panel_link_id: int,
    *,
    apartment_override: str = "",
    override_confirmed: bool = False,
    comment: str = "",
    issued_by: str = "",
) -> tuple[int, int]:
    with db() as conn:
        link = conn.execute(
            """
            SELECT pl.id, pl.apartment
            FROM uk_panel_links pl
            JOIN uk_groups g ON g.id = pl.uk_group_id
            WHERE pl.id = ? AND pl.uk_group_id = ?
              AND pl.active IS TRUE AND g.archived_at IS NULL
            """,
            (panel_link_id, group_id),
        ).fetchone()
        if not link:
            raise ValueError("Выбранная панель не закреплена за этой УК.")

        key = conn.execute(
            """
            SELECT id, hex_value, status
            FROM keys
            WHERE id = ?
            """,
            (key_id,),
        ).fetchone()
        if not key:
            raise ValueError("Ключ не найден.")
        if not _clean(key["hex_value"]):
            raise ValueError("Ключ без HEX нельзя выдать управляющей компании.")
        if key["status"] != "free":
            raise ValueError("Ключ уже имеет активное назначение.")

        apartment = _clean(apartment_override) or _clean(link["apartment"])
        if _clean(apartment_override) and apartment != _clean(link["apartment"]):
            if not override_confirmed:
                raise ValueError(
                    "Изменение квартиры только для операции требует подтверждения."
                )
        if not apartment:
            raise ValueError("Для панели не указан номер квартиры УК.")

        try:
            issue_cursor = conn.execute(
                """
                INSERT INTO uk_key_issues(
                    uk_group_id, key_id, status, comment, issued_by
                )
                VALUES (?, ?, 'pending', ?, ?)
                """,
                (
                    group_id,
                    key_id,
                    _clean(comment),
                    _clean(issued_by),
                ),
            )
            issue_id = int(issue_cursor.lastrowid)
            programming_cursor = conn.execute(
                """
                INSERT INTO uk_key_programmings(
                    issue_id, panel_link_id, apartment, is_primary
                )
                VALUES (?, ?, ?, TRUE)
                """,
                (issue_id, panel_link_id, apartment),
            )
            programming_id = int(programming_cursor.lastrowid)
            set_key_assignment_on_connection(
                conn,
                key_id,
                "uk",
                address=f"УК: {group_id}",
                apartment=apartment,
                uk_group_id=group_id,
                assigned_by=_clean(issued_by) or "Система",
                note=_clean(comment),
            )
            return issue_id, programming_id
        except IntegrityError as error:
            raise ValueError("Ключ уже выдан или записан на выбранную панель.") from error


def create_programming(
    group_id: int,
    issue_id: int,
    panel_link_id: int,
    *,
    apartment_override: str = "",
    override_confirmed: bool = False,
) -> int:
    with db() as conn:
        issue = conn.execute(
            """
            SELECT id FROM uk_key_issues
            WHERE id = ? AND uk_group_id = ?
              AND status IN ('pending', 'active')
            """,
            (issue_id, group_id),
        ).fetchone()
        if not issue:
            raise ValueError("Активная выдача ключа не найдена.")
        link = conn.execute(
            """
            SELECT id, apartment
            FROM uk_panel_links
            WHERE id = ? AND uk_group_id = ? AND active IS TRUE
            """,
            (panel_link_id, group_id),
        ).fetchone()
        if not link:
            raise ValueError("Панель не закреплена за выбранной УК.")
        apartment = _clean(apartment_override) or _clean(link["apartment"])
        if _clean(apartment_override) and apartment != _clean(link["apartment"]):
            if not override_confirmed:
                raise ValueError(
                    "Изменение квартиры только для операции требует подтверждения."
                )
        try:
            cursor = conn.execute(
                """
                INSERT INTO uk_key_programmings(
                    issue_id, panel_link_id, apartment, is_primary
                )
                VALUES (?, ?, ?, FALSE)
                """,
                (issue_id, panel_link_id, apartment),
            )
            return int(cursor.lastrowid)
        except IntegrityError as error:
            raise ValueError("Этот ключ уже связан с выбранной панелью.") from error


def record_crm_result(
    programming_id: int,
    *,
    operation: str,
    status: str,
    idempotency_key: str,
    safe_response: str,
    requested_by: str = "",
) -> int:
    if operation not in {"add", "remove"}:
        raise ValueError("Неизвестная CRM-операция.")
    normalized_status = status if status in {"success", "error", "dry_run"} else "error"

    try:
        with db() as conn:
            attempt = int(
                conn.execute(
                    """
                    SELECT COUNT(*) + 1
                    FROM uk_crm_operations
                    WHERE programming_id = ? AND operation = ?
                    """,
                    (programming_id, operation),
                ).fetchone()[0]
            )
            cursor = conn.execute(
                """
                INSERT INTO uk_crm_operations(
                    programming_id, operation, status, idempotency_key,
                    attempt_number, safe_response, requested_by, completed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    programming_id,
                    operation,
                    normalized_status,
                    idempotency_key,
                    attempt,
                    _clean(safe_response)[:1000],
                    _clean(requested_by),
                ),
            )

            if operation == "add":
                programming_status = {
                    "success": "success",
                    "dry_run": "dry_run",
                    "error": "error",
                }[normalized_status]
                conn.execute(
                    """
                    UPDATE uk_key_programmings
                    SET status = ?,
                        last_error = CASE WHEN ? = 'error' THEN ? ELSE '' END,
                        programmed_at = CASE
                            WHEN ? = 'success' THEN CURRENT_TIMESTAMP
                            ELSE programmed_at
                        END,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        programming_status,
                        normalized_status,
                        _clean(safe_response)[:1000],
                        normalized_status,
                        programming_id,
                    ),
                )
                if normalized_status == "success":
                    conn.execute(
                        """
                        UPDATE uk_key_issues
                        SET status = 'active', updated_at = CURRENT_TIMESTAMP
                        WHERE id = (
                            SELECT issue_id FROM uk_key_programmings WHERE id = ?
                        )
                        """,
                        (programming_id,),
                    )
            elif normalized_status == "success":
                programming = conn.execute(
                    """
                    SELECT issue_id FROM uk_key_programmings WHERE id = ?
                    """,
                    (programming_id,),
                ).fetchone()
                conn.execute(
                    """
                    UPDATE uk_key_programmings
                    SET active = FALSE, status = 'removed',
                        removed_at = CURRENT_TIMESTAMP, last_error = '',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (programming_id,),
                )
                _promote_primary_on_connection(conn, int(programming["issue_id"]))
                _release_empty_issue_on_connection(conn, int(programming["issue_id"]))
            elif normalized_status == "error":
                conn.execute(
                    """
                    UPDATE uk_key_programmings
                    SET last_error = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (_clean(safe_response)[:1000], programming_id),
                )

            return int(cursor.lastrowid)
    except IntegrityError as error:
        raise ValueError("Эта операция уже была обработана.") from error


def unlink_programming(programming_id: int) -> None:
    with db() as conn:
        programming = conn.execute(
            """
            SELECT issue_id
            FROM uk_key_programmings
            WHERE id = ? AND active IS TRUE
            """,
            (programming_id,),
        ).fetchone()
        if not programming:
            raise ValueError("Активная связь ключа с панелью не найдена.")
        conn.execute(
            """
            UPDATE uk_key_programmings
            SET active = FALSE, status = 'unlinked',
                unlinked_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (programming_id,),
        )
        _promote_primary_on_connection(conn, int(programming["issue_id"]))


def _promote_primary_on_connection(conn, issue_id: int) -> None:
    primary = conn.execute(
        """
        SELECT id FROM uk_key_programmings
        WHERE issue_id = ? AND active IS TRUE AND is_primary IS TRUE
        LIMIT 1
        """,
        (issue_id,),
    ).fetchone()
    if primary:
        return
    replacement = conn.execute(
        """
        SELECT id FROM uk_key_programmings
        WHERE issue_id = ? AND active IS TRUE
        ORDER BY created_at, id
        LIMIT 1
        """,
        (issue_id,),
    ).fetchone()
    if replacement:
        conn.execute(
            "UPDATE uk_key_programmings SET is_primary = TRUE WHERE id = ?",
            (replacement["id"],),
        )


def _release_empty_issue_on_connection(conn, issue_id: int) -> None:
    if conn.execute(
        """
        SELECT 1 FROM uk_key_programmings
        WHERE issue_id = ? AND active IS TRUE
        LIMIT 1
        """,
        (issue_id,),
    ).fetchone():
        return
    issue = conn.execute(
        "SELECT key_id FROM uk_key_issues WHERE id = ?",
        (issue_id,),
    ).fetchone()
    conn.execute(
        """
        UPDATE uk_key_issues
        SET status = 'released', released_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (issue_id,),
    )
    if issue:
        release_key_on_connection(
            conn,
            int(issue["key_id"]),
            "Удалён со всех панелей УК через CRM",
        )


def get_group_operations(group_id: int, limit: int = 30) -> list[dict]:
    with db() as conn:
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT *
                FROM operation_log
                WHERE uk_group_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (group_id, max(1, min(int(limit), 200))),
            )
        ]


def get_crm_operations(programming_id: int) -> list[dict]:
    with db() as conn:
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT *
                FROM uk_crm_operations
                WHERE programming_id = ?
                ORDER BY started_at DESC, id DESC
                """,
                (programming_id,),
            )
        ]
