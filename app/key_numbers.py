"""Shared comparison rules for accounting key numbers.

Stored values remain untouched.  Only purely numeric user input and purely
numeric database values are compared without leading zeroes.
"""

from __future__ import annotations

import re


_NUMERIC_KEY_NUMBER_RE = re.compile(r"^[0-9]+$")
_SQL_COLUMN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")


def is_numeric_key_number(value: object) -> bool:
    return bool(_NUMERIC_KEY_NUMBER_RE.fullmatch(str(value or "").strip()))


def normalize_key_number_for_lookup(value: object) -> str:
    """Return a comparison value without changing the stored representation."""

    raw = str(value or "").strip()
    if is_numeric_key_number(raw):
        return raw.lstrip("0") or "0"
    return raw.casefold()


def key_numbers_equal(left: object, right: object) -> bool:
    """Compare key numbers using numeric normalization only for digit strings."""

    left_raw = str(left or "").strip()
    right_raw = str(right or "").strip()
    if is_numeric_key_number(left_raw) and is_numeric_key_number(right_raw):
        return (
            normalize_key_number_for_lookup(left_raw)
            == normalize_key_number_for_lookup(right_raw)
        )
    return left_raw.casefold() == right_raw.casefold()


def infer_numeric_key_number_width(values: object) -> int | None:
    """Return a fixed stored width only when the type demonstrably uses one.

    A large unpadded value such as ``40630`` must not make the range ``1..50``
    render as ``00001..00050``.  We therefore preserve zero padding only when
    all stored numeric values have one fixed width and at least one of them
    actually contains a leading zero.
    """

    numeric_values = [
        str(value or "").strip()
        for value in values or ()
        if is_numeric_key_number(value)
    ]
    if not numeric_values:
        return None
    widths = {len(value) for value in numeric_values}
    if len(widths) != 1:
        return None
    if not any(len(value) > 1 and value.startswith("0") for value in numeric_values):
        return None
    return widths.pop()


def format_numeric_key_number(value: int, width: int | None = None) -> str:
    """Format a computed number without changing any stored key value."""

    text = str(int(value))
    return text.zfill(width) if width else text


def normalized_key_number_sql(column: str) -> str:
    """Build the PostgreSQL expression used by lookup queries and its index."""

    if not _SQL_COLUMN_RE.fullmatch(column):
        raise ValueError("Unsafe SQL column name for key-number lookup")
    return f"COALESCE(NULLIF(LTRIM(BTRIM({column}), '0'), ''), '0')"


def exact_key_number_sql(column: str, value: object) -> tuple[str, list[str]]:
    """Return a parameterized exact-match condition for user-entered input."""

    raw = str(value or "").strip()
    if is_numeric_key_number(raw):
        expression = normalized_key_number_sql(column)
        return (
            f"(BTRIM({column}) ~ '^[0-9]+$' AND {expression} = ?)",
            [normalize_key_number_for_lookup(raw)],
        )
    return f"LOWER(BTRIM({column})) = LOWER(?)", [raw]


def key_number_search_sql(
    column: str,
    value: object,
    *,
    pattern: str,
) -> tuple[str, list[str]]:
    """Preserve text search while adding normalized equality for numeric input."""

    raw = str(value or "").strip()
    if is_numeric_key_number(raw):
        exact_sql, exact_params = exact_key_number_sql(column, raw)
        return f"(SMART_NORM({column}) LIKE ? OR {exact_sql})", [pattern, *exact_params]
    return f"SMART_NORM({column}) LIKE ?", [pattern]
