"""Database-backed non-secret runtime settings shared by all workers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime

from app.db import db
from app.settings import settings


MONITOR_KEYS = (
    "panel_monitor_enabled",
    "panel_monitor_interval_seconds",
    "panel_monitor_concurrency",
    "panel_monitor_stale_seconds",
    "panel_manual_check_cooldown_seconds",
)


@dataclass(frozen=True)
class MonitorRuntimeSettings:
    panel_monitor_enabled: bool
    panel_monitor_interval_seconds: int
    panel_monitor_concurrency: int
    panel_monitor_stale_seconds: int
    panel_manual_check_cooldown_seconds: int
    updated_at: datetime | None = None
    updated_by: str = ""

    def values(self) -> dict[str, bool | int]:
        result = asdict(self)
        result.pop("updated_at", None)
        result.pop("updated_by", None)
        return result


def _defaults() -> dict[str, bool | int]:
    return {
        "panel_monitor_enabled": bool(settings.panel_monitor_enabled),
        "panel_monitor_interval_seconds": int(
            settings.panel_monitor_interval_seconds
        ),
        "panel_monitor_concurrency": int(settings.panel_monitor_concurrency),
        "panel_monitor_stale_seconds": int(settings.panel_monitor_stale_seconds),
        "panel_manual_check_cooldown_seconds": int(
            settings.panel_manual_check_cooldown_seconds
        ),
    }


def _parse_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    raise ValueError("Некорректное значение включения мониторинга")


def validate_monitor_settings(
    values: Mapping[str, object],
) -> dict[str, bool | int]:
    normalized = {
        "panel_monitor_enabled": _parse_bool(
            values.get("panel_monitor_enabled", False)
        ),
        "panel_monitor_interval_seconds": int(
            values["panel_monitor_interval_seconds"]
        ),
        "panel_monitor_concurrency": int(values["panel_monitor_concurrency"]),
        "panel_monitor_stale_seconds": int(
            values["panel_monitor_stale_seconds"]
        ),
        "panel_manual_check_cooldown_seconds": int(
            values["panel_manual_check_cooldown_seconds"]
        ),
    }
    interval = int(normalized["panel_monitor_interval_seconds"])
    concurrency = int(normalized["panel_monitor_concurrency"])
    stale = int(normalized["panel_monitor_stale_seconds"])
    cooldown = int(normalized["panel_manual_check_cooldown_seconds"])
    if not 60 <= interval <= 86400:
        raise ValueError("Интервал должен быть от 60 до 86400 секунд")
    if not 1 <= concurrency <= 50:
        raise ValueError("Параллельность должна быть от 1 до 50")
    if not interval <= stale <= 604800:
        raise ValueError(
            "Порог устаревания должен быть не меньше интервала и не больше 604800 секунд"
        )
    if not 1 <= cooldown <= 3600:
        raise ValueError("Пауза ручной проверки должна быть от 1 до 3600 секунд")
    return normalized


def get_monitor_runtime_settings() -> MonitorRuntimeSettings:
    values = _defaults()
    updated_at = None
    updated_by = ""
    with db() as conn:
        rows = conn.execute(
            """
            SELECT key, value, updated_at, updated_by
            FROM system_settings
            WHERE key IN (
                'panel_monitor_enabled',
                'panel_monitor_interval_seconds',
                'panel_monitor_concurrency',
                'panel_monitor_stale_seconds',
                'panel_manual_check_cooldown_seconds'
            )
            """,
        ).fetchall()
    for row in rows:
        key = row["key"]
        raw_value = row["value"]
        values[key] = (
            _parse_bool(raw_value)
            if key == "panel_monitor_enabled"
            else int(raw_value)
        )
        if row["updated_at"] and (
            updated_at is None or row["updated_at"] > updated_at
        ):
            updated_at = row["updated_at"]
            updated_by = row["updated_by"] or ""
    validated = validate_monitor_settings(values)
    return MonitorRuntimeSettings(
        **validated,
        updated_at=updated_at,
        updated_by=updated_by,
    )


def save_monitor_runtime_settings(
    values: Mapping[str, object],
    *,
    updated_by: str,
) -> MonitorRuntimeSettings:
    normalized = validate_monitor_settings(values)
    with db() as conn:
        for key in MONITOR_KEYS:
            value = normalized[key]
            serialized = (
                "true" if value is True else "false" if value is False else str(value)
            )
            conn.execute(
                """
                INSERT INTO system_settings(key, value, updated_at, updated_by)
                VALUES (?, ?, CURRENT_TIMESTAMP, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = EXCLUDED.value,
                    updated_at = EXCLUDED.updated_at,
                    updated_by = EXCLUDED.updated_by
                """,
                (key, serialized, updated_by.strip()),
            )
    return get_monitor_runtime_settings()
