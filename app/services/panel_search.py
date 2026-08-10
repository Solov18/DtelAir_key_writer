"""Shared read-only panel search for global and UK-scoped pickers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import re

from app.db import db
from app.search_utils import normalize_search_text, parse_assignment_search_query


class PanelSearchProfile(StrEnum):
    REGISTRY = "registry"
    PICKER_ALL = "picker_all"
    PICKER_UK = "picker_uk"
    UNIVERSAL = "universal"


@dataclass(frozen=True)
class PanelSearchResult:
    id: int
    address: str
    street: str
    house: str
    corpus: str
    point_name: str
    entrance: str
    mac: str
    ip: str
    active: bool
    group_id: int | None
    link_id: int | None
    status: str
    display_label: str
    rank: int

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class PanelSearchPage:
    items: list[PanelSearchResult]
    total: int


class PanelSearchService:
    @staticmethod
    def search(
        query: str = "",
        *,
        profile: PanelSearchProfile = PanelSearchProfile.PICKER_ALL,
        scope: str = "all",
        group_id: int | None = None,
        active_only: bool = False,
        limit: int = 60,
        exact_address: str = "",
        include_mac: bool = True,
        include_ip: bool = True,
    ) -> list[PanelSearchResult]:
        return PanelSearchService.search_page(
            query,
            profile=profile,
            scope=scope,
            group_id=group_id,
            active_only=active_only,
            limit=limit,
            exact_address=exact_address,
            include_mac=include_mac,
            include_ip=include_ip,
        ).items

    @staticmethod
    def search_page(
        query: str = "",
        *,
        profile: PanelSearchProfile = PanelSearchProfile.PICKER_ALL,
        scope: str = "all",
        group_id: int | None = None,
        active_only: bool = False,
        limit: int = 60,
        exact_address: str = "",
        include_mac: bool = True,
        include_ip: bool = True,
    ) -> PanelSearchPage:
        normalized = normalize_search_text(query)
        if scope not in {"all", "uk"}:
            raise ValueError("Unknown panel search scope")
        if scope == "uk" and group_id is None:
            raise ValueError("group_id is required for UK panel search")

        fields = ["p.address", "p.entrance", "p.name", "p.tags", "CAST(p.id AS TEXT)"]
        if include_mac:
            fields.append("p.mac")
        if include_ip:
            fields.append("p.ip")
        searchable = f"CONCAT_WS(' ', {', '.join(fields)})"
        conditions = ["1 = 1"]
        params: list[object] = []
        join = ""
        select_link = "NULL::INTEGER AS link_id, NULL::INTEGER AS group_id"
        if scope == "uk":
            join = "JOIN uk_panel_links pl ON pl.panel_id = p.id AND pl.active IS TRUE"
            conditions.append("pl.uk_group_id = ?")
            params.append(int(group_id))
            select_link = "pl.id AS link_id, pl.uk_group_id AS group_id"
        if active_only:
            conditions.append("p.enabled = 1")
        if normalized:
            # Match every meaningful fragment independently.  This preserves
            # punctuation-insensitive lookup and also finds e.g. "parking
            # lift" in a value stored as "parking and lift".
            terms = [
                normalize_search_text(part)
                for part in re.findall(r"[0-9A-Za-zА-Яа-яЁё]+", query or "")
                if normalize_search_text(part)
            ] or [normalized]
            for term in terms:
                conditions.append(f"SMART_NORM({searchable}) LIKE ?")
                params.append(f"%{term}%")
        if exact_address:
            conditions.append("SMART_NORM(p.address) = ?")
            params.append(normalize_search_text(exact_address))

        query_limit = max(1, min(int(limit), 100))
        preserve_registry_order = profile in {
            PanelSearchProfile.REGISTRY,
            PanelSearchProfile.PICKER_ALL,
        }
        rank_order = "1" if preserve_registry_order else "search_rank"
        with db() as conn:
            rows = conn.execute(
                f"""
                SELECT p.id, p.address, p.entrance, p.name, p.mac, p.ip,
                       p.enabled, p.api_status, {select_link},
                       COUNT(*) OVER() AS total_count,
                       CASE
                         WHEN ? <> '' AND SMART_NORM(p.address) = ? THEN 0
                         WHEN ? <> '' AND SMART_NORM({searchable}) LIKE ? THEN 1
                         ELSE 2
                       END AS search_rank
                FROM panels p
                {join}
                WHERE {' AND '.join(conditions)}
                ORDER BY {rank_order}, LOWER(p.address), p.address,
                         LOWER(COALESCE(p.entrance, '')),
                         LOWER(COALESCE(p.name, '')), p.id
                LIMIT ?
                """,
                [normalized, normalized, normalized, f"{normalized}%", *params, query_limit],
            ).fetchall()

        results = []
        total = int(rows[0]["total_count"]) if rows else 0
        for row in rows:
            item = dict(row)
            address = str(item.get("address") or "")
            parsed_address = parse_assignment_search_query(address)
            house = str(parsed_address.get("house") or "")
            corpus = house.split("/", 1)[1] if "/" in house else ""
            street = " ".join(parsed_address.get("street_tokens") or [])
            entrance = str(item.get("entrance") or "")
            point_name = entrance or str(item.get("name") or "")
            results.append(
                PanelSearchResult(
                    id=int(item["id"]), address=address, street=street,
                    house=house, corpus=corpus, point_name=point_name,
                    entrance=entrance, mac=str(item.get("mac") or ""),
                    ip=str(item.get("ip") or ""), active=bool(item.get("enabled")),
                    group_id=int(item["group_id"]) if item.get("group_id") is not None else None,
                    link_id=int(item["link_id"]) if item.get("link_id") is not None else None,
                    status=str(item.get("api_status") or "unknown"),
                    display_label=" · ".join(
                        filter(None, [address, point_name, str(item.get("mac") or "")])
                    ),
                    rank=int(item.get("search_rank") or 0),
                )
            )
        return PanelSearchPage(items=results, total=total)
