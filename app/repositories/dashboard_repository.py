"""Compact PostgreSQL reads used by the main dashboard."""

from __future__ import annotations

from app.db import db
from app.panel_health import SUPPLY_VOLTAGE_MAX, SUPPLY_VOLTAGE_MIN


def get_dashboard_snapshot() -> dict:
    """Return all dashboard counters and saved monitor state in one query."""

    with db() as conn:
        row = conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM employees) AS employees,
                (
                    SELECT COUNT(*)
                    FROM uk_groups
                    WHERE archived_at IS NULL
                ) AS uk,
                (SELECT COUNT(*) FROM panels) AS panels,
                (
                    SELECT COUNT(*)
                    FROM keys
                    WHERE TRIM(COALESCE(hex_value, '')) <> ''
                ) AS keys,
                (SELECT COUNT(*) FROM operation_log) AS logs,
                (
                    SELECT COUNT(*)
                    FROM panels
                    WHERE enabled = 1
                      AND last_checked_at IS NOT NULL
                      AND api_status = 'online'
                ) AS panels_online,
                (
                    SELECT COUNT(*)
                    FROM panels
                    WHERE enabled = 1
                      AND last_checked_at IS NOT NULL
                      AND api_status = 'offline'
                ) AS panels_offline,
                (
                    SELECT COUNT(*)
                    FROM panels
                    WHERE enabled = 1
                      AND last_checked_at IS NOT NULL
                      AND supply_voltage IS NOT NULL
                      AND supply_voltage NOT BETWEEN ? AND ?
                ) AS panels_voltage_alert,
                (
                    SELECT COUNT(*)
                    FROM panels
                    WHERE enabled = 1
                      AND last_checked_at IS NOT NULL
                      AND sip_registered IS NOT NULL
                ) AS panels_sip_known,
                (
                    SELECT COUNT(*)
                    FROM panels
                    WHERE enabled = 1
                      AND last_checked_at IS NOT NULL
                      AND sip_registered = 0
                ) AS panels_sip_failed,
                monitor.status AS monitor_status,
                monitor.completed AS monitor_completed,
                monitor.failed AS monitor_failed,
                monitor.finished_at AS monitor_finished_at
            FROM (
                SELECT status, completed, failed, finished_at
                FROM panel_monitor_state
                WHERE finished_at IS NOT NULL
                ORDER BY finished_at DESC
                LIMIT 1
            ) AS monitor
            RIGHT JOIN (SELECT 1 AS singleton) AS seed ON TRUE
            """,
            (SUPPLY_VOLTAGE_MIN, SUPPLY_VOLTAGE_MAX),
        ).fetchone()

    result = dict(row)
    for key in (
        "employees",
        "uk",
        "panels",
        "keys",
        "logs",
        "panels_online",
        "panels_offline",
        "panels_voltage_alert",
        "panels_sip_known",
        "panels_sip_failed",
        "monitor_completed",
        "monitor_failed",
    ):
        result[key] = int(result.get(key) or 0)
    return result
