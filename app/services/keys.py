import re

from app.db import db


def normalize_hex_value(value: str) -> str:
    value = (value or "").strip().upper()
    value = value.replace(" ", "").replace(":", "").replace("-", "")

    if value.startswith("000000") and len(value) == 14:
        value = value[6:]

    return value


def find_keys(number_or_hex: str, key_type_id: int | None = None) -> list[dict]:
    from app.services.key_search import KeySearchService

    return [
        {
            **item.as_legacy_dict(),
            "key_type_id": item.type_id,
            "key_type": item.type,
            "type_enabled": 1,
        }
        for item in KeySearchService.exact_lookup(
            number_or_hex,
            type_id=key_type_id,
        )
    ]


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
