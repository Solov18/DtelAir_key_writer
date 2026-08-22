"""Compact PostgreSQL reads used by the main dashboard."""

from __future__ import annotations

from app.db import db
from app.panel_health import (
    SUPPLY_VOLTAGE_MAX, SUPPLY_VOLTAGE_MIN, TEMPERATURE_ALERT_C,
    UPTIME_ALERT_MAX_SECONDS, UPTIME_ALERT_MIN_SECONDS,
)
from app.repositories.log_repository import JOURNAL_NOISE_ACTIONS


def get_dashboard_snapshot() -> dict:
    """Return all dashboard counters and saved monitor state in one query."""

    noise_placeholders = ", ".join("?" for _ in JOURNAL_NOISE_ACTIONS)
    with db() as conn:
        row = conn.execute(
            f"""
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
                (
                    SELECT COUNT(*)
                    FROM operation_log
                    WHERE action NOT IN ({noise_placeholders})
                ) AS logs,
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
                      AND api_status IN ('offline', 'timeout')
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
                    SELECT COUNT(*) FROM panels
                    WHERE enabled = 1 AND last_checked_at IS NOT NULL
                      AND temperature > ?
                ) AS panels_temperature_alert,
                (
                    SELECT COUNT(*) FROM panels
                    WHERE enabled = 1 AND last_checked_at IS NOT NULL
                      AND api_status IN ('online', 'sip_auth_error') AND uptime_seconds IS NOT NULL
                      AND (uptime_seconds < ? OR uptime_seconds > ?)
                ) AS panels_uptime_alert,
                (
                    SELECT COUNT(*)
                    FROM panels
                    WHERE enabled = 1
                      AND last_checked_at IS NOT NULL
                      AND (api_status = 'sip_auth_error' OR sip_registered IS NOT NULL)
                ) AS panels_sip_known,
                (
                    SELECT COUNT(*)
                    FROM panels
                    WHERE enabled = 1
                      AND last_checked_at IS NOT NULL
                      AND (api_status = 'sip_auth_error' OR sip_registered = 0)
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
            (
                *JOURNAL_NOISE_ACTIONS,
                SUPPLY_VOLTAGE_MIN, SUPPLY_VOLTAGE_MAX,
                TEMPERATURE_ALERT_C,
                UPTIME_ALERT_MIN_SECONDS, UPTIME_ALERT_MAX_SECONDS,
            ),
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
        "panels_temperature_alert",
        "panels_uptime_alert",
        "panels_sip_known",
        "panels_sip_failed",
        "monitor_completed",
        "monitor_failed",
    ):
        result[key] = int(result.get(key) or 0)
    return result
