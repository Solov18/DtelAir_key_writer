"""Shared rules for interpreting persisted panel health values."""

from __future__ import annotations


SUPPLY_VOLTAGE_MIN = 12.7
SUPPLY_VOLTAGE_MAX = 13.7
TEMPERATURE_ALERT_C = 100.0
UPTIME_ALERT_MIN_SECONDS = 10 * 60
UPTIME_ALERT_MAX_SECONDS = 30 * 24 * 60 * 60


def supply_voltage_tone(value: object) -> str:
    """Return the UI tone for a saved panel supply-voltage measurement."""

    if value in (None, ""):
        return "missing"
    try:
        voltage = float(value)
    except (TypeError, ValueError):
        return "missing"
    return (
        "normal"
        if SUPPLY_VOLTAGE_MIN <= voltage <= SUPPLY_VOLTAGE_MAX
        else "alert"
    )


def supply_voltage_needs_attention(value: object) -> bool:
    return supply_voltage_tone(value) == "alert"


def temperature_tone(value: object) -> str:
    if value in (None, ""):
        return "missing"
    try:
        return "alert" if float(value) > TEMPERATURE_ALERT_C else "normal"
    except (TypeError, ValueError):
        return "missing"


def uptime_tone(value: object, *, is_reachable: bool) -> str:
    if value in (None, "") or not is_reachable:
        return "missing"
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return "missing"
    return (
        "alert"
        if seconds < UPTIME_ALERT_MIN_SECONDS or seconds > UPTIME_ALERT_MAX_SECONDS
        else "normal"
    )
