import re
from typing import Iterable

from app.db import db
from app.services.parser import (
    find_address_candidates,
    normalize_house_variants,
)


def normalize(value: str) -> str:
    return normalize_house_variants(value)


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

    panels = [dict(row) for row in rows]
    exact = [
        panel
        for panel in panels
        if normalize(panel["address"]) == query
    ]
    if exact:
        return exact

    candidates = find_address_candidates(address, limit=3)
    if not candidates:
        return []

    best = candidates[0]
    second_score = candidates[1]["confidence"] if len(candidates) > 1 else 0.0
    if (
        best["confidence"] < 0.76
        or best["confidence"] - second_score < 0.045
    ):
        return []

    target = normalize(best["address"])
    for row in rows:
        panel = dict(row)
        if normalize(panel["address"]) == target:
            exact.append(panel)
    return exact


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
