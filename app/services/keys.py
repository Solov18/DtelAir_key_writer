import re

from app.db import db


def normalize_hex_value(value: str) -> str:
    value = (value or "").strip().upper()
    value = value.replace(" ", "").replace(":", "").replace("-", "")

    if value.startswith("000000") and len(value) == 14:
        value = value[6:]

    return value


def _key_select() -> str:
    return """
        SELECT
            k.*,
            kt.name AS type_name,
            kt.color AS type_color,
            kt.enabled AS type_enabled
        FROM keys k
        JOIN key_types kt ON kt.id = k.key_type_id
    """


def find_keys(number_or_hex: str, key_type_id: int | None = None) -> list[dict]:
    raw = (number_or_hex or "").strip()
    if not raw:
        return []

    hex_value = normalize_hex_value(raw)
    params: list = [raw]
    type_filter = ""

    if key_type_id:
        type_filter = " AND k.key_type_id = ?"
        params.append(key_type_id)

    with db() as conn:
        number_rows = conn.execute(
            _key_select()
            + f"""
                WHERE k.number = ? COLLATE NOCASE
                  AND TRIM(k.hex_value) <> ''
                {type_filter}
                ORDER BY kt.name COLLATE NOCASE, k.id
            """,
            params,
        ).fetchall()

        if number_rows:
            return [dict(row) for row in number_rows]

        if re.fullmatch(r"[0-9A-F]{6,16}", hex_value):
            hex_rows = conn.execute(
                _key_select()
                + """
                    WHERE UPPER(k.hex_value) = ?
                    ORDER BY kt.name COLLATE NOCASE, k.id
                """,
                (hex_value,),
            ).fetchall()
            return [dict(row) for row in hex_rows]

    return []


def find_key(number_or_hex: str, key_type_id: int | None = None):
    matches = find_keys(number_or_hex, key_type_id)

    if len(matches) == 1:
        return matches[0]

    if len(matches) > 1:
        return {
            "_ambiguous": True,
            "number": (number_or_hex or "").strip(),
            "hex_value": "",
            "key_type": "Требуется выбрать тип",
            "matches": matches,
        }

    hex_value = normalize_hex_value(number_or_hex)
    if re.fullmatch(r"[0-9A-F]{8}", hex_value):
        return {
            "number": "",
            "hex_value": hex_value,
            "key_type": "HEX вручную",
            "type_name": "HEX вручную",
        }

    return None


def is_ambiguous_key(key: dict | None) -> bool:
    return bool(key and key.get("_ambiguous"))
