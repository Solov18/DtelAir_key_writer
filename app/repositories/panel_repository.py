import re

from app.db import db


def normalize_mac(value: str) -> str:
    """
    Приводит MAC-адрес к формату 08:13:CD:00:1D:C2.
    """

    raw = re.sub(
        r"[^0-9a-fA-F]",
        "",
        value or "",
    ).upper()

    if len(raw) != 12:
        return (value or "").strip().upper()

    return ":".join(
        raw[index:index + 2]
        for index in range(0, 12, 2)
    )


def normalize_ip(value: str) -> str:
    """
    Оставляет только IP или имя хоста без протокола и пути.
    """

    result = (value or "").strip()

    result = re.sub(
        r"^https?://",
        "",
        result,
        flags=re.IGNORECASE,
    )

    result = result.split("/", maxsplit=1)[0]

    return result.strip()


def build_internal_name(
    address: str,
    entrance: str,
) -> str:
    """
    Поле name обязательно в старой структуре базы.

    В интерфейсе название больше не показывается,
    поэтому формируем его автоматически.
    """

    address = (address or "").strip()
    entrance = (entrance or "").strip()

    if entrance:
        return f"{address} {entrance}"

    return address


def get_enabled_panels() -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                address,
                entrance,
                name,
                mac,
                ip,
                tags,
                enabled,
                created_at
            FROM panels
            WHERE enabled = 1
            ORDER BY
                address,
                entrance,
                id
            """
        ).fetchall()

    return [
        dict(row)
        for row in rows
    ]


def get_panel_by_id(
    panel_id: int,
) -> dict | None:
    with db() as conn:
        row = conn.execute(
            """
            SELECT
                id,
                address,
                entrance,
                name,
                mac,
                ip,
                tags,
                enabled,
                created_at
            FROM panels
            WHERE id = ?
            """,
            (panel_id,),
        ).fetchone()

    if row is None:
        return None

    return dict(row)


def get_panels_by_ids(
    panel_ids: list[int],
) -> list[dict]:
    if not panel_ids:
        return []

    placeholders = ",".join(
        "?"
        for _ in panel_ids
    )

    with db() as conn:
        rows = conn.execute(
            f"""
            SELECT
                id,
                address,
                entrance,
                name,
                mac,
                ip,
                tags,
                enabled,
                created_at
            FROM panels
            WHERE enabled = 1
              AND id IN ({placeholders})
            ORDER BY
                address,
                entrance,
                id
            """,
            panel_ids,
        ).fetchall()

    return [
        dict(row)
        for row in rows
    ]


def get_panels_by_tag(
    tag: str,
) -> list[dict]:
    """
    Оставлено для совместимости с другими разделами проекта.
    """

    with db() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                address,
                entrance,
                name,
                mac,
                ip,
                tags,
                enabled,
                created_at
            FROM panels
            WHERE enabled = 1
              AND tags LIKE ?
            ORDER BY
                address,
                entrance,
                id
            """,
            (f"%{(tag or '').strip()}%",),
        ).fetchall()

    return [
        dict(row)
        for row in rows
    ]


def create_or_update_panel(
    address: str,
    entrance: str = "",
    name: str = "",
    mac: str = "",
    tags: str = "",
    ip: str = "",
) -> None:
    """
    Добавляет новую панель или обновляет существующую по MAC.

    name и tags оставлены в аргументах для совместимости
    со старым импортом, но название формируется автоматически.
    """

    clean_address = (address or "").strip()
    clean_entrance = (entrance or "").strip()
    clean_mac = normalize_mac(mac)
    clean_ip = normalize_ip(ip)

    if not clean_address:
        raise ValueError("Адрес панели не указан")

    if not clean_mac:
        raise ValueError("MAC-адрес панели не указан")

    internal_name = build_internal_name(
        clean_address,
        clean_entrance,
    )

    with db() as conn:
        conn.execute(
            """
            INSERT INTO panels(
                address,
                entrance,
                name,
                mac,
                tags,
                ip,
                enabled
            )
            VALUES (?, ?, ?, ?, ?, ?, 1)

            ON CONFLICT(mac) DO UPDATE SET
                address = excluded.address,
                entrance = excluded.entrance,
                name = excluded.name,
                ip = excluded.ip,
                enabled = 1
            """,
            (
                clean_address,
                clean_entrance,
                internal_name,
                clean_mac,
                (tags or "").strip(),
                clean_ip,
            ),
        )


def update_panel(
    panel_id: int,
    address: str,
    entrance: str = "",
    name: str = "",
    mac: str = "",
    tags: str = "",
    ip: str = "",
) -> None:
    """
    Изменяет существующую панель.
    """

    clean_address = (address or "").strip()
    clean_entrance = (entrance or "").strip()
    clean_mac = normalize_mac(mac)
    clean_ip = normalize_ip(ip)

    if not clean_address:
        raise ValueError("Адрес панели не указан")

    if not clean_mac:
        raise ValueError("MAC-адрес панели не указан")

    internal_name = build_internal_name(
        clean_address,
        clean_entrance,
    )

    with db() as conn:
        conn.execute(
            """
            UPDATE panels
            SET
                address = ?,
                entrance = ?,
                name = ?,
                mac = ?,
                ip = ?
            WHERE id = ?
            """,
            (
                clean_address,
                clean_entrance,
                internal_name,
                clean_mac,
                clean_ip,
                panel_id,
            ),
        )


def delete_panel(
    panel_id: int,
) -> None:
    """
    Полностью удаляет панель из базы.

    Сначала удаляет её связи с управляющими компаниями,
    затем саму панель.
    """

    with db() as conn:
        conn.execute(
            """
            DELETE FROM uk_group_panels
            WHERE panel_id = ?
            """,
            (panel_id,),
        )

        conn.execute(
            """
            DELETE FROM panels
            WHERE id = ?
            """,
            (panel_id,),
        )