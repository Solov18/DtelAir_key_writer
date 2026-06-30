import re

from app.db import db


def normalize_hex_value(value: str) -> str:
    value = (value or "").strip().upper()
    value = value.replace(" ", "").replace(":", "").replace("-", "")

    if value.startswith("000000") and len(value) == 14:
        value = value[6:]

    return value


def find_key(number_or_hex: str):
    raw = (number_or_hex or "").strip()
    hex_value = normalize_hex_value(raw)

    with db() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM keys
            WHERE number = ?
            """,
            (raw,),
        ).fetchone()

        if row:
            return dict(row)

        if re.fullmatch(r"[0-9A-F]{8}", hex_value):
            row = conn.execute(
                """
                SELECT *
                FROM keys
                WHERE UPPER(hex_value) = ?
                """,
                (hex_value,),
            ).fetchone()

            if row:
                return dict(row)

            return {
                "number": "",
                "hex_value": hex_value,
                "key_type": "HEX вручную",
            }

    return None