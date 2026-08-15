"""Read-only key search shared by registries, pickers and exact lookup.

The service deliberately owns no assignment or write behaviour.  Profiles
only select matching/ranking rules; callers remain responsible for adapting
the DTO to their existing HTTP contracts.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import re

from app.db import db
from app.search_utils import normalize_search_text
from app.key_numbers import (
    exact_key_number_sql,
    is_numeric_key_number,
    key_number_search_sql,
    key_numbers_equal,
    normalize_key_number_for_lookup,
    normalized_key_number_sql,
)


class KeySearchProfile(StrEnum):
    REGISTRY = "registry"
    PICKER = "picker"
    UNIVERSAL = "universal"
    EXACT_LOOKUP = "exact_lookup"
    MESSAGE = "message"


@dataclass(frozen=True)
class KeySearchResult:
    id: int
    number: str
    hex: str
    status: str
    type_id: int
    type: str
    type_color: str
    is_available: bool
    occupied: bool
    current_owner: str
    display_label: str
    match_type: str
    rank: int

    def as_dict(self) -> dict:
        return asdict(self)

    def as_legacy_dict(self) -> dict:
        return {
            "id": self.id,
            "number": self.number,
            "hex_value": self.hex,
            "status": self.status,
            "type_id": self.type_id,
            "type_name": self.type,
            "type_color": self.type_color,
            "available": self.is_available,
            "search_rank": self.rank,
        }


def normalize_key_hex(value: str) -> str:
    normalized = re.sub(r"[^0-9A-Fa-f]", "", value or "").upper()
    if normalized.startswith("000000") and len(normalized) == 14:
        normalized = normalized[6:]
    return normalized


def normalize_key_number(value: str) -> str:
    """Compatibility alias for the shared lookup normalization rule."""
    return normalize_key_number_for_lookup(value)


def _compact_query(value: str) -> str:
    return re.sub(r"[^0-9A-Za-zА-Яа-яЁё]+", "", value or "").upper()


class KeySearchService:
    @staticmethod
    def search(
        query: str = "",
        *,
        profile: KeySearchProfile = KeySearchProfile.PICKER,
        type_id: int | None = None,
        available_only: bool = False,
        include_occupied: bool = True,
        exact_only: bool = False,
        limit: int = 12,
        exclude_owner_id: int | None = None,
    ) -> list[KeySearchResult]:
        del exclude_owner_id  # Reserved by the read contract; no old query used it.
        raw = (query or "").strip()
        normalized = normalize_search_text(raw)
        if not normalized and not available_only:
            return []

        compact = _compact_query(raw)
        numeric = compact if compact.isdigit() else ""
        numeric_unpadded = normalize_key_number_for_lookup(numeric) if numeric else ""
        normalized_number_sql = normalized_key_number_sql("k.number")
        conditions = ["kt.enabled = 1"]
        if profile != KeySearchProfile.EXACT_LOOKUP:
            conditions.append("BTRIM(k.hex_value) <> ''")
        params: list[object] = []

        if normalized:
            if exact_only or profile == KeySearchProfile.EXACT_LOOKUP:
                number_sql, number_params = exact_key_number_sql("k.number", raw)
                conditions.append(
                    f"(({number_sql}) OR UPPER(k.hex_value) = ?)"
                )
                params.extend([*number_params, normalize_key_hex(raw)])
            else:
                search_value = "CONCAT_WS(' ', kt.name, k.number, k.hex_value)"
                terms = [
                    normalize_search_text(part)
                    for part in re.findall(r"[0-9A-Za-zА-Яа-яЁё]+", raw)
                    if normalize_search_text(part)
                ] or [normalized]
                prefix_term = terms[-1] if len(terms) > 1 else ""
                for term in terms[:-1] if prefix_term else terms:
                    if is_numeric_key_number(term):
                        number_sql, number_params = key_number_search_sql(
                            "k.number", term, pattern=f"%{term}%"
                        )
                        conditions.append(
                            f"(SMART_NORM({search_value}) LIKE ? OR {number_sql})"
                        )
                        params.extend([f"%{term}%", *number_params])
                    else:
                        conditions.append(f"SMART_NORM({search_value}) LIKE ?")
                        params.append(f"%{term}%")
                if prefix_term:
                    number_sql, number_params = key_number_search_sql(
                        "k.number", prefix_term, pattern=f"{prefix_term}%"
                    )
                    conditions.append(
                        f"({number_sql} OR SMART_NORM(k.hex_value) LIKE ?)"
                    )
                    params.extend([*number_params, f"{prefix_term}%"])
        if type_id is not None:
            conditions.append("kt.id = ?")
            params.append(int(type_id))

        available_sql = """(
            k.status = 'free' AND NOT EXISTS (
                SELECT 1 FROM uk_key_issues ki
                WHERE ki.key_id = k.id
                  AND ki.status IN ('pending', 'active')
            )
        )"""
        if available_only:
            conditions.append(available_sql)
        elif not include_occupied:
            conditions.append("k.status = 'free'")

        query_limit = max(1, min(int(limit), 100))
        with db() as conn:
            rows = conn.execute(
                f"""
                WITH ranked AS (
                    SELECT k.id, k.number, k.hex_value, k.status,
                           kt.id AS type_id, kt.name AS type_name,
                           kt.color AS type_color,
                           {available_sql} AS available,
                           CASE
                               WHEN UPPER(REGEXP_REPLACE(k.hex_value, '[^0-9A-Za-z]', '', 'g')) = ? THEN 0
                               WHEN ? <> '' AND BTRIM(k.number) ~ '^[0-9]+$'
                                    AND {normalized_number_sql} = ? THEN 0
                               WHEN SMART_NORM(k.number) = ? OR SMART_NORM(k.hex_value) = ? THEN 1
                               WHEN SMART_NORM(k.number) LIKE ? OR SMART_NORM(k.hex_value) LIKE ? THEN 2
                               ELSE 3
                           END AS search_rank
                    FROM keys k
                    JOIN key_types kt ON kt.id = k.key_type_id
                    WHERE {' AND '.join(conditions)}
                    ORDER BY search_rank,
                             CASE WHEN {available_sql} THEN 0 ELSE 1 END,
                             LOWER(kt.name), LENGTH(k.number), LOWER(k.number), k.id
                    LIMIT ?
                )
                SELECT ranked.*,
                       COALESCE(owner.current_owner, '') AS current_owner
                FROM ranked
                LEFT JOIN LATERAL (
                    SELECT STRING_AGG(
                        NULLIF(CONCAT_WS(', ',
                            NULLIF(ka.assignment_type, ''),
                            NULLIF(ka.address, ''),
                            CASE WHEN NULLIF(ka.apartment, '') IS NOT NULL
                                 THEN 'кв. ' || ka.apartment ELSE NULL END,
                            NULLIF(ka.note, '')
                        ), ''), '; ' ORDER BY ka.id
                    ) AS current_owner
                    FROM key_assignments ka
                    WHERE ka.key_id = ranked.id AND ka.active = 1
                ) owner ON TRUE
                ORDER BY ranked.search_rank,
                         CASE WHEN ranked.available THEN 0 ELSE 1 END,
                         LOWER(ranked.type_name), LENGTH(ranked.number),
                         LOWER(ranked.number), ranked.id
                """,
                [compact, numeric_unpadded, numeric_unpadded, normalized, normalized,
                 f"{normalized}%", f"{normalized}%", *params, query_limit],
            ).fetchall()

        results: list[KeySearchResult] = []
        for row in rows:
            item = dict(row)
            rank = int(item["search_rank"])
            match_type = "exact" if rank <= 1 else "prefix" if rank == 2 else "contains"
            results.append(
                KeySearchResult(
                    id=int(item["id"]),
                    number=str(item.get("number") or ""),
                    hex=str(item.get("hex_value") or ""),
                    status=str(item.get("status") or ""),
                    type_id=int(item["type_id"]),
                    type=str(item.get("type_name") or ""),
                    type_color=str(item.get("type_color") or ""),
                    is_available=bool(item.get("available")),
                    occupied=not bool(item.get("available")),
                    current_owner=str(item.get("current_owner") or ""),
                    display_label=f"{item.get('type_name') or ''} · №{item.get('number') or ''} · {item.get('hex_value') or ''}",
                    match_type=match_type,
                    rank=rank,
                )
            )
        return results

    @classmethod
    def exact_lookup(
        cls, value: str, *, type_id: int | None = None, limit: int = 100
    ) -> list[KeySearchResult]:
        raw = str(value or "").strip()
        if not raw:
            return []
        # Preserve the old priority: an exact printed number wins over HEX.
        number_matches = cls.search(
            raw,
            profile=KeySearchProfile.EXACT_LOOKUP,
            type_id=type_id,
            exact_only=True,
            limit=limit,
        )
        exact_numbers = [
            item for item in number_matches
            if key_numbers_equal(item.number, raw)
        ]
        if exact_numbers:
            return exact_numbers
        normalized_hex = normalize_key_hex(raw)
        if not re.fullmatch(r"[0-9A-F]{6,16}", normalized_hex):
            return []
        return [item for item in number_matches if item.hex.upper() == normalized_hex]
