import math

from app.db import db
from app.repositories.key_repository import (
    release_key_on_connection,
    set_key_assignment_on_connection,
)
from app.search_utils import normalize_search_text


def get_groups() -> list[dict]:
    with db() as conn:
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT
                    g.*,
                    (
                        SELECT COUNT(*)
                        FROM uk_group_panels gp
                        WHERE gp.group_id = g.id
                    ) AS panels_count,
                    (
                        SELECT COUNT(*)
                        FROM uk_group_keys gk
                        WHERE gk.group_id = g.id
                    ) AS keys_count,
                    (
                        SELECT COUNT(*)
                        FROM uk_notification_drafts nd
                        WHERE nd.group_id = g.id
                    ) AS notification_drafts_count
                FROM uk_groups g
                ORDER BY g.name COLLATE NOCASE
                """
            )
        ]


def get_group(group_id: int) -> dict | None:
    with db() as conn:
        row = conn.execute(
            """
            SELECT
                g.*,
                (
                    SELECT COUNT(*)
                    FROM uk_group_panels gp
                    WHERE gp.group_id = g.id
                ) AS panels_count,
                (
                    SELECT COUNT(*)
                    FROM uk_group_keys gk
                    WHERE gk.group_id = g.id
                ) AS keys_count,
                (
                    SELECT COUNT(*)
                    FROM uk_notification_drafts nd
                    WHERE nd.group_id = g.id
                ) AS notification_drafts_count
            FROM uk_groups g
            WHERE g.id = ?
            """,
            (group_id,),
        ).fetchone()

        return dict(row) if row else None


def get_group_statistics() -> dict:
    with db() as conn:
        row = conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM uk_groups) AS total,
                (SELECT COUNT(*) FROM uk_group_panels) AS panels,
                (SELECT COUNT(*) FROM uk_group_keys) AS keys,
                (
                    SELECT COUNT(*)
                    FROM uk_groups
                    WHERE cooperation_status = 'partner'
                ) AS partners,
                (
                    SELECT COUNT(*)
                    FROM uk_groups
                    WHERE cooperation_status IN ('contacted', 'negotiation')
                ) AS in_progress,
                (
                    SELECT COUNT(*)
                    FROM uk_notification_drafts
                ) AS notification_drafts
            """
        ).fetchone()

        return dict(row)


def get_group_page(
    query: str = "",
    cooperation_state: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict:
    page = max(1, int(page))
    page_size = max(1, min(100, int(page_size)))
    normalized_state = (
        cooperation_state
        if cooperation_state
        in {"potential", "contacted", "negotiation", "partner", "paused"}
        else ""
    )
    normalized_query = normalize_search_text(query)
    params: list[object] = []
    conditions = ["1 = 1"]

    if normalized_query:
        pattern = f"%{normalized_query}%"
        conditions.append(
            """
            (
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
                OR EXISTS (
                    SELECT 1
                    FROM uk_notification_drafts search_nd
                    WHERE search_nd.group_id = g.id
                      AND (
                        SMART_NORM(search_nd.title) LIKE ?
                        OR SMART_NORM(search_nd.body) LIKE ?
                      )
                )
            )
            """
        )
        params.extend([pattern] * 12)

    if normalized_state:
        conditions.append("g.cooperation_status = ?")
        params.append(normalized_state)

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
                g.*,
                (
                    SELECT COUNT(*)
                    FROM uk_group_panels gp
                    WHERE gp.group_id = g.id
                ) AS panels_count,
                (
                    SELECT COUNT(*)
                    FROM uk_group_keys gk
                    WHERE gk.group_id = g.id
                ) AS keys_count,
                (
                    SELECT COUNT(*)
                    FROM uk_notification_drafts nd
                    WHERE nd.group_id = g.id
                ) AS notification_drafts_count,
                (
                    SELECT nd.title
                    FROM uk_notification_drafts nd
                    WHERE nd.group_id = g.id
                    ORDER BY nd.created_at DESC, nd.id DESC
                    LIMIT 1
                ) AS latest_notification_title,
                (
                    SELECT nd.created_at
                    FROM uk_notification_drafts nd
                    WHERE nd.group_id = g.id
                    ORDER BY nd.created_at DESC, nd.id DESC
                    LIMIT 1
                ) AS latest_notification_at
            FROM uk_groups g
            WHERE {where_sql}
            ORDER BY g.name COLLATE NOCASE, g.id
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
    contract_number: str = "",
    created_by: str = "",
    cooperation_status: str = "potential",
    account_manager: str = "",
    next_contact_at: str = "",
    cooperation_note: str = "",
) -> int:
    cooperation_status = (
        cooperation_status
        if cooperation_status
        in {"potential", "contacted", "negotiation", "partner", "paused"}
        else "potential"
    )
    with db() as conn:
        conn.execute(
            """
            INSERT INTO uk_groups(
                name,
                note,
                crm_login,
                crm_password,
                legal_name,
                contact_name,
                phone,
                email,
                legal_address,
                contract_number,
                created_by,
                cooperation_status,
                account_manager,
                next_contact_at,
                cooperation_note,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(name)
            DO UPDATE SET
                note = excluded.note,
                legal_name = excluded.legal_name,
                contact_name = excluded.contact_name,
                phone = excluded.phone,
                email = excluded.email,
                legal_address = excluded.legal_address,
                contract_number = excluded.contract_number,
                cooperation_status = excluded.cooperation_status,
                account_manager = excluded.account_manager,
                next_contact_at = excluded.next_contact_at,
                cooperation_note = excluded.cooperation_note,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                name.strip(),
                note.strip(),
                crm_login.strip(),
                crm_password.strip(),
                legal_name.strip(),
                contact_name.strip(),
                phone.strip(),
                email.strip(),
                legal_address.strip(),
                contract_number.strip(),
                created_by.strip(),
                cooperation_status,
                account_manager.strip(),
                next_contact_at.strip(),
                cooperation_note.strip(),
            ),
        )
        row = conn.execute(
            "SELECT id FROM uk_groups WHERE name = ? COLLATE NOCASE",
            (name.strip(),),
        ).fetchone()
        return int(row["id"])


def update_group(
    group_id: int,
    name: str,
    note: str = "",
    legal_name: str = "",
    contact_name: str = "",
    phone: str = "",
    email: str = "",
    legal_address: str = "",
    contract_number: str = "",
    cooperation_status: str = "potential",
    account_manager: str = "",
    next_contact_at: str = "",
    cooperation_note: str = "",
) -> None:
    cooperation_status = (
        cooperation_status
        if cooperation_status
        in {"potential", "contacted", "negotiation", "partner", "paused"}
        else "potential"
    )
    with db() as conn:
        conn.execute(
            """
            UPDATE uk_groups
            SET
                name = ?,
                note = ?,
                legal_name = ?,
                contact_name = ?,
                phone = ?,
                email = ?,
                legal_address = ?,
                contract_number = ?,
                cooperation_status = ?,
                account_manager = ?,
                next_contact_at = ?,
                cooperation_note = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                name.strip(),
                note.strip(),
                legal_name.strip(),
                contact_name.strip(),
                phone.strip(),
                email.strip(),
                legal_address.strip(),
                contract_number.strip(),
                cooperation_status,
                account_manager.strip(),
                next_contact_at.strip(),
                cooperation_note.strip(),
                group_id,
            ),
        )


def update_group_credentials(
    group_id: int,
    note: str = "",
    crm_login: str = "",
    crm_password: str = "",
) -> None:
    with db() as conn:
        conn.execute(
            """
            UPDATE uk_groups
            SET
                note = ?,
                crm_login = ?,
                crm_password = ?
            WHERE id = ?
            """,
            (
                note.strip(),
                crm_login.strip(),
                crm_password.strip(),
                group_id,
            ),
        )


def get_notification_drafts(
    group_id: int,
    limit: int = 50,
) -> list[dict]:
    with db() as conn:
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT *
                FROM uk_notification_drafts
                WHERE group_id = ?
                ORDER BY datetime(created_at) DESC, id DESC
                LIMIT ?
                """,
                (group_id, max(1, min(int(limit), 200))),
            )
        ]


def save_notification_draft(
    group_id: int,
    title: str,
    body: str,
    category: str = "announcement",
    channel: str = "dtel",
    audience: str = "all",
    audience_details: str = "",
    created_by: str = "",
) -> int:
    clean_title = title.strip()
    clean_body = body.strip()
    if not clean_title or not clean_body:
        raise ValueError("Заголовок и текст уведомления обязательны")

    category = (
        category
        if category in {"announcement", "emergency", "works", "payment", "survey"}
        else "announcement"
    )
    channel = (
        channel
        if channel in {"dtel", "push", "sms", "email", "messenger"}
        else "dtel"
    )
    audience = (
        audience
        if audience in {"all", "address", "entrance", "custom"}
        else "all"
    )

    with db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO uk_notification_drafts(
                group_id,
                title,
                body,
                category,
                channel,
                audience,
                audience_details,
                created_by
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                group_id,
                clean_title,
                clean_body,
                category,
                channel,
                audience,
                audience_details.strip(),
                created_by.strip(),
            ),
        )
        return int(cursor.lastrowid)


def delete_notification_draft(group_id: int, draft_id: int) -> None:
    with db() as conn:
        conn.execute(
            """
            DELETE FROM uk_notification_drafts
            WHERE id = ? AND group_id = ?
            """,
            (draft_id, group_id),
        )


def delete_group(group_id: int) -> None:
    with db() as conn:
        assigned_keys = conn.execute(
            """
            SELECT key_id
            FROM key_assignments
            WHERE assignment_type = 'uk'
              AND uk_group_id = ?
              AND active = 1
            """,
            (group_id,),
        ).fetchall()

        for item in assigned_keys:
            release_key_on_connection(
                conn,
                int(item["key_id"]),
                "Управляющая компания удалена",
            )

        conn.execute(
            """
            DELETE FROM uk_group_panels
            WHERE group_id = ?
            """,
            (group_id,),
        )

        conn.execute(
            """
            DELETE FROM uk_group_keys
            WHERE group_id = ?
            """,
            (group_id,),
        )

        conn.execute(
            """
            DELETE FROM uk_groups
            WHERE id = ?
            """,
            (group_id,),
        )


def get_group_panels(group_id: int) -> list[dict]:
    with db() as conn:
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT p.*
                FROM panels p
                JOIN uk_group_panels gp
                    ON gp.panel_id = p.id
                WHERE gp.group_id = ?
                ORDER BY
                    p.address,
                    p.entrance,
                    p.name
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
                SELECT *
                FROM panels
                WHERE enabled = 1
                  AND id NOT IN (
                      SELECT panel_id
                      FROM uk_group_panels
                      WHERE group_id = ?
                  )
                ORDER BY
                    address,
                    entrance,
                    name
                """,
                (group_id,),
            )
        ]


def add_panels(group_id: int, panel_ids: list[int]) -> None:
    if not panel_ids:
        return

    with db() as conn:
        conn.executemany(
            """
            INSERT OR IGNORE INTO uk_group_panels(
                group_id,
                panel_id
            )
            VALUES (?, ?)
            """,
            [
                (group_id, int(panel_id))
                for panel_id in panel_ids
            ],
        )


def remove_panel(group_id: int, panel_id: int) -> None:
    with db() as conn:
        conn.execute(
            """
            DELETE FROM uk_group_panels
            WHERE group_id = ?
              AND panel_id = ?
            """,
            (
                group_id,
                panel_id,
            ),
        )


def get_group_keys(group_id: int) -> list[dict]:
    with db() as conn:
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT k.*, kt.name AS type_name, kt.color AS type_color
                FROM keys k
                JOIN uk_group_keys gk
                    ON gk.key_id = k.id
                LEFT JOIN key_types kt
                    ON kt.id = k.key_type_id
                WHERE gk.group_id = ?
                ORDER BY k.number
                """,
                (group_id,),
            )
        ]


def add_keys(
    group_id: int,
    key_numbers: list[str],
    key_type_id: int | None = None,
) -> dict:
    added = []
    not_found = []
    ambiguous = []

    with db() as conn:
        for number in key_numbers:
            clean_number = number.strip()

            if not clean_number:
                continue

            matches = conn.execute(
                """
                SELECT k.*, kt.name AS type_name, kt.color AS type_color
                FROM keys k
                LEFT JOIN key_types kt ON kt.id = k.key_type_id
                WHERE k.number = ?
                  AND TRIM(k.hex_value) <> ''
                  AND (? IS NULL OR k.key_type_id = ?)
                ORDER BY k.id
                """,
                (clean_number, key_type_id, key_type_id),
            ).fetchall()

            if not matches:
                not_found.append(clean_number)
                continue
            if len(matches) > 1:
                ambiguous.append(clean_number)
                continue

            key = matches[0]

            conn.execute(
                """
                INSERT OR IGNORE INTO uk_group_keys(
                    group_id,
                    key_id
                )
                VALUES (?, ?)
                """,
                (
                    group_id,
                    key["id"],
                ),
            )

            set_key_assignment_on_connection(
                conn,
                int(key["id"]),
                "uk",
                uk_group_id=group_id,
                assigned_by="Учёт УК",
            )

            added.append(dict(key))

    return {
        "added": added,
        "not_found": not_found,
        "ambiguous": ambiguous,
    }


def remove_key(group_id: int, key_id: int) -> None:
    with db() as conn:
        conn.execute(
            """
            DELETE FROM uk_group_keys
            WHERE group_id = ?
              AND key_id = ?
            """,
            (
                group_id,
                key_id,
            ),
        )

        active_assignment = conn.execute(
            """
            SELECT id
            FROM key_assignments
            WHERE key_id = ?
              AND assignment_type = 'uk'
              AND uk_group_id = ?
              AND active = 1
            LIMIT 1
            """,
            (key_id, group_id),
        ).fetchone()

        if active_assignment:
            release_key_on_connection(
                conn,
                key_id,
                "Удалён из управляющей компании",
            )
