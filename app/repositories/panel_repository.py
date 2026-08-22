import math
import re
from datetime import datetime, timezone

from app.db import db
from app.search_utils import normalize_search_text
from app.panel_health import (
    SUPPLY_VOLTAGE_MAX,
    SUPPLY_VOLTAGE_MIN,
    TEMPERATURE_ALERT_C,
    UPTIME_ALERT_MAX_SECONDS,
    UPTIME_ALERT_MIN_SECONDS,
    supply_voltage_tone,
    temperature_tone,
    uptime_tone,
)


PANEL_STATUS_LABELS = {
    "online": "В сети",
    "offline": "Нет связи",
    "timeout": "Тайм-аут",
    "sip_auth_error": "Ошибка SIP-авторизации",
    "other_error": "Другая ошибка",
    "auth_error": "Ошибка доступа",
    "error": "Ошибка API",
    "no_ip": "Нет IP",
    "not_configured": "API не настроен",
    "unknown": "Не проверено",
    "checking": "Проверяется",
    "disabled": "Отключена",
}

PANEL_STATUS_TONES = {
    "online": "success",
    "offline": "warning",
    "timeout": "warning",
    "sip_auth_error": "error",
    "other_error": "error",
    "auth_error": "error",
    "error": "error",
    "no_ip": "muted",
    "not_configured": "warning",
    "unknown": "muted",
    "checking": "info",
    "disabled": "muted",
}


def format_uptime(seconds) -> str:
    if seconds in (None, ""):
        return "—"
    try:
        value = max(0, int(seconds))
    except (TypeError, ValueError):
        return "—"
    days, remainder = divmod(value, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    if days:
        return f"{days} дн. {hours:02d}:{minutes:02d}"
    return f"{hours:02d}:{minutes:02d}"


def _voltage_tone(value) -> str:
    return supply_voltage_tone(value)


def _is_stale(value, stale_after_seconds: int) -> bool:
    if not isinstance(value, datetime):
        return False
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - value).total_seconds() > stale_after_seconds


def normalize_panel_row(
    row,
    *,
    checking_panel_ids: set[int] | None = None,
    stale_after_seconds: int = 600,
) -> dict:
    item = dict(row)
    if not item.get("enabled"):
        status = "disabled"
    elif checking_panel_ids and int(item["id"]) in checking_panel_ids:
        status = "checking"
    elif not item.get("last_checked_at"):
        status = "unknown"
    else:
        status = item.get("api_status") or "unknown"
    if status not in PANEL_STATUS_LABELS:
        status = "error"
    # A timeout means that the panel could not be reached.  Keep the persisted
    # diagnostic status for support, but present it consistently as offline.
    display_status = "offline" if status == "timeout" else status
    item["network_status"] = display_status
    item["diagnostic_status"] = status
    item["status_name"] = PANEL_STATUS_LABELS[display_status]
    item["status_tone"] = PANEL_STATUS_TONES[display_status]
    item["uptime_text"] = format_uptime(item.get("uptime_seconds"))
    item["voltage_tone"] = _voltage_tone(item.get("supply_voltage"))
    item["temperature_tone"] = temperature_tone(item.get("temperature"))
    item["uptime_tone"] = uptime_tone(
        item.get("uptime_seconds"),
        is_reachable=status in {"online", "sip_auth_error"},
    )
    item["is_stale"] = bool(
        item.get("enabled")
        and display_status == "online"
        and item.get("last_checked_at")
        and _is_stale(item.get("last_checked_at"), stale_after_seconds)
    )
    configured_mac = normalize_mac(item.get("mac", ""))
    reported_mac = normalize_mac(item.get("reported_mac", ""))
    item["mac_matches"] = not reported_mac or configured_mac == reported_mac
    return item


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


def get_enabled_panels(skip_checked_within_seconds: int = 0) -> list[dict]:
    recent_condition = ""
    params: tuple = ()
    if skip_checked_within_seconds > 0:
        recent_condition = (
            "AND (last_checked_at IS NULL OR "
            "last_checked_at < CURRENT_TIMESTAMP - (? * INTERVAL '1 second'))"
        )
        params = (max(1, int(skip_checked_within_seconds)),)
    with db() as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM panels
            WHERE enabled = 1
              {recent_condition}
            ORDER BY
                address,
                entrance,
                id
            """,
            params,
        ).fetchall()

    return [normalize_panel_row(row) for row in rows]


def get_panel_by_id(
    panel_id: int,
) -> dict | None:
    with db() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM panels
            WHERE id = ?
            """,
            (panel_id,),
        ).fetchone()

    if row is None:
        return None

    return normalize_panel_row(row)


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
            SELECT *
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

    return [normalize_panel_row(row) for row in rows]


def get_panels_by_tag(
    tag: str,
) -> list[dict]:
    """
    Оставлено для совместимости с другими разделами проекта.
    """

    with db() as conn:
        rows = conn.execute(
            """
            SELECT *
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

    return [normalize_panel_row(row) for row in rows]


def get_panel_statistics(stale_after_seconds: int = 600) -> dict:
    with db() as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN enabled = 1 AND last_checked_at IS NOT NULL AND api_status = 'online' THEN 1 ELSE 0 END) AS online,
                SUM(CASE WHEN enabled = 1 AND last_checked_at IS NOT NULL AND api_status IN ('offline', 'timeout') THEN 1 ELSE 0 END) AS offline,
                SUM(CASE WHEN enabled = 1 AND last_checked_at IS NOT NULL AND api_status IN ('other_error', 'auth_error', 'error', 'no_ip', 'not_configured') THEN 1 ELSE 0 END) AS errors,
                SUM(CASE WHEN enabled = 0 THEN 1 ELSE 0 END) AS disabled,
                SUM(
                    CASE
                        WHEN enabled = 1
                         AND last_checked_at IS NOT NULL
                         AND (api_status = 'sip_auth_error' OR sip_registered = 0)
                        THEN 1 ELSE 0
                    END
                ) AS sip_failed,
                SUM(
                    CASE
                        WHEN enabled = 1
                         AND last_checked_at IS NULL
                        THEN 1 ELSE 0
                    END
                ) AS unchecked,
                SUM(
                    CASE
                        WHEN enabled = 1
                         AND last_checked_at IS NOT NULL
                         AND api_status = 'online'
                         AND last_checked_at < CURRENT_TIMESTAMP - (? * INTERVAL '1 second')
                        THEN 1 ELSE 0
                    END
                ) AS stale,
                SUM(CASE WHEN enabled = 1 AND last_checked_at IS NOT NULL AND supply_voltage IS NOT NULL AND supply_voltage NOT BETWEEN ? AND ? THEN 1 ELSE 0 END) AS voltage_alert,
                SUM(CASE WHEN enabled = 1 AND last_checked_at IS NOT NULL AND temperature > ? THEN 1 ELSE 0 END) AS temperature_alert,
                SUM(CASE WHEN enabled = 1 AND last_checked_at IS NOT NULL AND api_status IN ('online', 'sip_auth_error') AND uptime_seconds IS NOT NULL AND (uptime_seconds < ? OR uptime_seconds > ?) THEN 1 ELSE 0 END) AS uptime_alert,
                MAX(last_checked_at) AS last_checked_at
            FROM panels
            """,
            (
                max(30, int(stale_after_seconds)),
                SUPPLY_VOLTAGE_MIN,
                SUPPLY_VOLTAGE_MAX,
                TEMPERATURE_ALERT_C,
                UPTIME_ALERT_MIN_SECONDS,
                UPTIME_ALERT_MAX_SECONDS,
            ),
        ).fetchone()
    result = dict(row)
    for key in (
        "total",
        "online",
        "offline",
        "errors",
        "disabled",
        "sip_failed",
        "unchecked",
        "stale",
        "voltage_alert",
        "temperature_alert",
        "uptime_alert",
    ):
        result[key] = int(result.get(key) or 0)
    result["online_percent"] = (
        round(result["online"] / result["total"] * 100)
        if result["total"]
        else 0
    )
    return result


def get_panel_filter_options() -> dict:
    with db() as conn:
        addresses = [
            row[0]
            for row in conn.execute(
                """
                SELECT MIN(address) AS address
                FROM panels
                WHERE address <> ''
                GROUP BY SMART_NORM(address)
                ORDER BY SMART_NORM(MIN(address))
                """
            )
        ]
        entrances = [
            row[0]
            for row in conn.execute(
                """
                SELECT MIN(entrance) AS entrance
                FROM panels
                WHERE entrance <> ''
                GROUP BY SMART_NORM(entrance)
                ORDER BY SMART_NORM(MIN(entrance))
                """
            )
        ]
    return {
        "addresses": addresses,
        "entrances": entrances,
        "address_options": [(value, value) for value in addresses],
        "entrance_options": [(value, value) for value in entrances],
    }


def resolve_exact_panel_address(address: str) -> str | None:
    """Return the canonical registry address for an exact normalized match."""
    clean_address = (address or "").strip()
    if not clean_address:
        return None
    with db() as conn:
        row = conn.execute(
            """
            SELECT MIN(address) AS address
            FROM panels
            WHERE SMART_NORM(address) = SMART_NORM(?)
              AND BTRIM(COALESCE(address, '')) <> ''
            """,
            (clean_address,),
        ).fetchone()
    return str(row[0]) if row and row[0] else None


def get_panels_for_exact_address(address: str) -> list[dict]:
    """Return enabled panels belonging to exactly one registry address."""
    canonical = resolve_exact_panel_address(address)
    if not canonical:
        return []
    with db() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM panels
            WHERE enabled = 1
              AND SMART_NORM(address) = SMART_NORM(?)
            ORDER BY entrance, name, id
            """,
            (canonical,),
        ).fetchall()
    return [normalize_panel_row(row) for row in rows]


def get_panel_page(
    *,
    query: str = "",
    status: str = "",
    address: str = "",
    entrance: str = "",
    page: int = 1,
    page_size: int = 20,
    stale_after_seconds: int = 600,
    checking_panel_ids: set[int] | None = None,
) -> dict:
    conditions = ["1 = 1"]
    params: list = []
    normalized_query = normalize_search_text(query)
    if normalized_query:
        pattern = f"%{normalized_query}%"
        conditions.append(
            """
            (
                SMART_NORM(CAST(id AS TEXT)) LIKE ?
                OR SMART_NORM(address) LIKE ?
                OR SMART_NORM(entrance) LIKE ?
                OR SMART_NORM(name) LIKE ?
                OR SMART_NORM(mac) LIKE ?
                OR SMART_NORM(ip) LIKE ?
                OR SMART_NORM(device_model) LIKE ?
                OR SMART_NORM(firmware_version) LIKE ?
                OR SMART_NORM(
                    CONCAT_WS(' ', address, entrance, name, tags, mac, CAST(id AS TEXT))
                ) LIKE ?
            )
            """
        )
        params.extend([pattern] * 9)

    if address:
        conditions.append("address = ?")
        params.append(address)
    if entrance:
        conditions.append("entrance = ?")
        params.append(entrance)

    if status == "disabled":
        conditions.append("enabled = 0")
    elif status == "online":
        conditions.append("enabled = 1 AND last_checked_at IS NOT NULL AND api_status = 'online'")
    elif status == "offline":
        conditions.append("enabled = 1 AND last_checked_at IS NOT NULL AND api_status IN ('offline', 'timeout')")
    elif status == "timeout":
        conditions.append("enabled = 1 AND last_checked_at IS NOT NULL AND api_status = 'timeout'")
    elif status == "sip_auth_error":
        conditions.append("enabled = 1 AND last_checked_at IS NOT NULL AND api_status = 'sip_auth_error'")
    elif status == "other_error":
        conditions.append("enabled = 1 AND last_checked_at IS NOT NULL AND api_status = 'other_error'")
    elif status == "error":
        conditions.append(
            "enabled = 1 AND last_checked_at IS NOT NULL "
            "AND api_status IN ('other_error', 'auth_error', 'error', 'no_ip', 'not_configured')"
        )
    elif status == "unchecked":
        conditions.append("enabled = 1 AND last_checked_at IS NULL")
    elif status == "stale":
        conditions.append(
            "enabled = 1 AND last_checked_at IS NOT NULL "
            "AND api_status = 'online' "
            "AND last_checked_at < CURRENT_TIMESTAMP - (? * INTERVAL '1 second')"
        )
        params.append(max(30, int(stale_after_seconds)))
    elif status == "voltage_alert":
        conditions.append(
            "enabled = 1 AND last_checked_at IS NOT NULL "
            "AND supply_voltage IS NOT NULL "
            "AND supply_voltage NOT BETWEEN ? AND ?"
        )
        params.extend([SUPPLY_VOLTAGE_MIN, SUPPLY_VOLTAGE_MAX])
    elif status == "temperature_alert":
        conditions.append(
            "enabled = 1 AND last_checked_at IS NOT NULL AND temperature > ?"
        )
        params.append(TEMPERATURE_ALERT_C)
    elif status == "uptime_alert":
        conditions.append(
            "enabled = 1 AND last_checked_at IS NOT NULL AND api_status IN ('online', 'sip_auth_error') "
            "AND uptime_seconds IS NOT NULL AND (uptime_seconds < ? OR uptime_seconds > ?)"
        )
        params.extend([UPTIME_ALERT_MIN_SECONDS, UPTIME_ALERT_MAX_SECONDS])
    elif status == "sip_error":
        conditions.append(
            "enabled = 1 AND last_checked_at IS NOT NULL "
            "AND (api_status = 'sip_auth_error' OR sip_registered = 0)"
        )

    where_sql = " AND ".join(conditions)
    page_size = min(100, max(10, int(page_size or 20)))
    page = max(1, int(page or 1))

    with db() as conn:
        total = int(
            conn.execute(
                f"SELECT COUNT(*) FROM panels WHERE {where_sql}",
                params,
            ).fetchone()[0]
        )
        pages = max(1, math.ceil(total / page_size))
        page = min(page, pages)
        rows = conn.execute(
            f"""
            SELECT *
            FROM panels
            WHERE {where_sql}
            ORDER BY
                LOWER(address),
                address,
                LOWER(COALESCE(entrance, '')),
                COALESCE(entrance, ''),
                id
            LIMIT ? OFFSET ?
            """,
            [*params, page_size, (page - 1) * page_size],
        ).fetchall()

    return {
        "items": [
            normalize_panel_row(
                row,
                checking_panel_ids=checking_panel_ids,
                stale_after_seconds=stale_after_seconds,
            )
            for row in rows
        ],
        "total": total,
        "page": page,
        "pages": pages,
        "page_size": page_size,
    }


def get_panels_for_status_refresh(panel_ids: list[int]) -> list[dict]:
    clean_ids = sorted({int(panel_id) for panel_id in panel_ids if int(panel_id) > 0})
    if not clean_ids:
        return []
    placeholders = ",".join("?" for _ in clean_ids)
    with db() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM panels
            WHERE id IN ({placeholders}) AND enabled = 1
            ORDER BY id
            """,
            clean_ids,
        ).fetchall()
    return [dict(row) for row in rows]


def get_all_panels() -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM panels
            ORDER BY
                LOWER(address),
                address,
                LOWER(COALESCE(entrance, '')),
                COALESCE(entrance, ''),
                id
            """
        ).fetchall()
    return [normalize_panel_row(row) for row in rows]


def update_panel_api_status(panel_id: int, result: dict) -> None:
    status = result.get("status", "error")
    last_online_sql = (
        "CURRENT_TIMESTAMP"
        if status in {"online", "sip_auth_error"}
        else "last_online_at"
    )
    sip_registered = result.get("sip_registered")
    if sip_registered is not None:
        sip_registered = 1 if bool(sip_registered) else 0
    with db() as conn:
        conn.execute(
            f"""
            UPDATE panels
            SET api_status = ?,
                last_checked_at = CURRENT_TIMESTAMP,
                last_online_at = {last_online_sql},
                response_time_ms = ?,
                device_model = COALESCE(?, device_model),
                firmware_version = COALESCE(?, firmware_version),
                temperature = COALESCE(?, temperature),
                supply_voltage = COALESCE(?, supply_voltage),
                uptime_seconds = COALESCE(?, uptime_seconds),
                sip_registered = COALESCE(?, sip_registered),
                reported_mac = COALESCE(?, reported_mac),
                last_error = ?
            WHERE id = ?
            """,
            (
                status,
                result.get("response_time_ms"),
                result.get("device_model"),
                result.get("firmware_version"),
                result.get("temperature"),
                result.get("supply_voltage"),
                result.get("uptime_seconds"),
                sip_registered,
                result.get("reported_mac"),
                result.get("last_error", ""),
                panel_id,
            ),
        )


def seconds_since_last_check(panel_id: int) -> float | None:
    with db() as conn:
        row = conn.execute(
            """
            SELECT EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - last_checked_at))
            FROM panels
            WHERE id = ? AND last_checked_at IS NOT NULL
            """,
            (panel_id,),
        ).fetchone()
    if not row or row[0] is None:
        return None
    return max(0.0, float(row[0]))


def set_panel_enabled(panel_id: int, enabled: bool) -> None:
    with db() as conn:
        cursor = conn.execute(
            "UPDATE panels SET enabled = ? WHERE id = ?",
            (1 if enabled else 0, panel_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("Панель не найдена")


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

    Исторические и активные связи с УК не удаляются автоматически.
    """

    with db() as conn:
        linked = conn.execute(
            """
            SELECT 1
            FROM uk_panel_links
            WHERE panel_id = ?
            LIMIT 1
            """,
            (panel_id,),
        ).fetchone()
        if linked:
            raise ValueError(
                "Панель связана с историей УК и не может быть удалена."
            )

        conn.execute(
            """
            DELETE FROM panels
            WHERE id = ?
            """,
            (panel_id,),
        )
