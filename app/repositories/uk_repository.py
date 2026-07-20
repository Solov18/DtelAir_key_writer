from app.db import db
from app.repositories.key_repository import (
    release_key_on_connection,
    set_key_assignment_on_connection,
)


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
                    ) AS keys_count
                FROM uk_groups g
                ORDER BY g.name
                """
            )
        ]


def get_group(group_id: int) -> dict | None:
    with db() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM uk_groups
            WHERE id = ?
            """,
            (group_id,),
        ).fetchone()

        return dict(row) if row else None


def save_group(
    name: str,
    note: str = "",
    crm_login: str = "",
    crm_password: str = "",
) -> None:
    with db() as conn:
        conn.execute(
            """
            INSERT INTO uk_groups(
                name,
                note,
                crm_login,
                crm_password
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(name)
            DO UPDATE SET
                note = excluded.note,
                crm_login = excluded.crm_login,
                crm_password = excluded.crm_password
            """,
            (
                name.strip(),
                note.strip(),
                crm_login.strip(),
                crm_password.strip(),
            ),
        )


def update_group(
    group_id: int,
    name: str,
    note: str = "",
    crm_login: str = "",
    crm_password: str = "",
) -> None:
    with db() as conn:
        conn.execute(
            """
            UPDATE uk_groups
            SET
                name = ?,
                note = ?,
                crm_login = ?,
                crm_password = ?
            WHERE id = ?
            """,
            (
                name.strip(),
                note.strip(),
                crm_login.strip(),
                crm_password.strip(),
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
