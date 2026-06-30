from app.db import db


def get_enabled_panels() -> list[dict]:
    with db() as conn:
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT *
                FROM panels
                WHERE enabled = 1
                ORDER BY address, entrance, name
                """
            )
        ]


def get_panels_by_ids(panel_ids: list[int]) -> list[dict]:
    if not panel_ids:
        return []

    placeholders = ",".join("?" for _ in panel_ids)

    with db() as conn:
        return [
            dict(row)
            for row in conn.execute(
                f"""
                SELECT *
                FROM panels
                WHERE enabled = 1
                  AND id IN ({placeholders})
                ORDER BY address, entrance, name
                """,
                panel_ids,
            )
        ]


def get_panels_by_tag(tag: str) -> list[dict]:
    with db() as conn:
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT *
                FROM panels
                WHERE enabled = 1
                  AND tags LIKE ?
                ORDER BY address, entrance, name
                """,
                (f"%{tag}%",),
            )
        ]


def create_or_update_panel(
    address: str,
    entrance: str,
    name: str,
    mac: str,
    tags: str,
) -> None:
    with db() as conn:
        conn.execute(
            """
            INSERT INTO panels(address, entrance, name, mac, tags)
            VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(mac) DO UPDATE SET
                address = excluded.address,
                entrance = excluded.entrance,
                name = excluded.name,
                tags = excluded.tags
            """,
            (
                address.strip(),
                entrance.strip(),
                name.strip(),
                mac.strip().upper(),
                tags.strip(),
            ),
        )


def update_panel(
    panel_id: int,
    address: str,
    entrance: str,
    name: str,
    mac: str,
    tags: str,
) -> None:
    with db() as conn:
        conn.execute(
            """
            UPDATE panels
            SET address = ?,
                entrance = ?,
                name = ?,
                mac = ?,
                tags = ?
            WHERE id = ?
            """,
            (
                address.strip(),
                entrance.strip(),
                name.strip(),
                mac.strip().upper(),
                tags.strip(),
                panel_id,
            ),
        )


def soft_delete_panel(panel_id: int) -> None:
    with db() as conn:
        conn.execute(
            """
            UPDATE panels
            SET enabled = 0
            WHERE id = ?
            """,
            (panel_id,),
        )