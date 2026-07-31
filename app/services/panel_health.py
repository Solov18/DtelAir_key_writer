"""Shared rules for interpreting persisted panel health values."""

from __future__ import annotations


SUPPLY_VOLTAGE_MIN = 12.8
SUPPLY_VOLTAGE_MAX = 13.5


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
