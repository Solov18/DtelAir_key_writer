import re
from typing import Iterable

from app.db import db


def normalize(value: str) -> str:
    value = (value or "").lower().replace("ё", "е")
    value = re.sub(r"\b(улица|ул\.|ул|дом|д\.)\b", "", value)
    value = re.sub(r"\s+", " ", value).strip()

    return value


def find_panels_by_address(address: str):
    query = normalize(address)

    with db() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM panels
            WHERE enabled = 1
            ORDER BY address, entrance, name
            """
        ).fetchall()

    if not query:
        return []

    result = []

    for row in rows:
        panel = dict(row)
        panel_address = normalize(panel["address"])

        if query in panel_address or panel_address in query:
            result.append(panel)

    return result


def get_panels(
    panel_ids: Iterable[int] | None = None,
    tag: str | None = None,
):
    with db() as conn:
        if panel_ids:
            ids = list(panel_ids)

            if not ids:
                return []

            placeholders = ",".join("?" for _ in ids)

            return [
                dict(row)
                for row in conn.execute(
                    f"""
                    SELECT *
                    FROM panels
                    WHERE enabled = 1
                      AND id IN ({placeholders})
                    ORDER BY address, name
                    """,
                    ids,
                )
            ]

        if tag:
            return [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT *
                    FROM panels
                    WHERE enabled = 1
                      AND tags LIKE ?
                    ORDER BY address, name
                    """,
                    (f"%{tag}%",),
                )
            ]

        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT *
                FROM panels
                WHERE enabled = 1
                ORDER BY address, name
                """
            )
        ]


def split_panel_address(full_address: str) -> tuple[str, str]:
    text = (full_address or "").strip()
    text = re.sub(r"\s+", " ", text)

    if "," not in text:
        return text, ""

    parts = [
        part.strip()
        for part in text.split(",")
        if part.strip()
    ]

    address = parts[0]
    entrance = ", ".join(parts[1:])

    return address, entrance