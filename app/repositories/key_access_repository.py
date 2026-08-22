"""Authoritative active access projection for physical keys."""

from app.db import db


SERVICE_ASSIGNMENT_TYPES = {"employee", "uk", "contractor", "other", "service"}


def access_type_for_assignment(assignment_type: str) -> str:
    return "resident" if assignment_type == "resident" else "service"


def get_active_accesses(key_id: int) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT ka.*, COUNT(kps.id) AS panel_count
            FROM key_accesses ka
            LEFT JOIN key_panel_states kps
              ON kps.access_id = ka.id
             AND kps.state IN ('active', 'pending_delete')
            WHERE ka.key_id = ? AND ka.active = 1
            GROUP BY ka.id
            ORDER BY ka.is_primary DESC, ka.assigned_at, ka.id
            """,
            (key_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_active_accesses_with_panels(key_id: int) -> list[dict]:
    """Return every current logical access with its current physical points.

    ``key_assignments`` remains the backwards-compatible primary owner record;
    this projection is the authoritative list shown by the key card and used
    for multi-address resident/service access.
    """
    accesses = get_active_accesses(key_id)
    for access in accesses:
        access["panels"] = get_access_panels(int(access["id"]))
    return accesses


def ensure_access(
    key_id: int,
    *,
    assignment_type: str,
    address: str = "",
    apartment: str = "",
    owner_name: str = "",
    assignment_id: int | None = None,
    primary: bool = False,
    source: str = "write",
    created_by: str = "",
    note: str = "",
) -> int:
    access_type = access_type_for_assignment(assignment_type)
    address = str(address or "").strip()
    apartment = str(apartment or "").strip()
    with db() as conn:
        if primary:
            conn.execute(
                "UPDATE key_accesses SET is_primary = 0 WHERE key_id = ? AND active = 1",
                (key_id,),
            )
        row = conn.execute(
            """
            SELECT id FROM key_accesses
            WHERE key_id = ? AND access_type = ? AND address = ? AND apartment = ?
              AND active = 1
            ORDER BY id DESC LIMIT 1
            """,
            (key_id, access_type, address, apartment),
        ).fetchone()
        if row:
            access_id = int(row[0])
            conn.execute(
                """
                UPDATE key_accesses
                SET assignment_id = COALESCE(?, assignment_id),
                    owner_name = CASE WHEN ? <> '' THEN ? ELSE owner_name END,
                    is_primary = CASE WHEN ? THEN 1 ELSE is_primary END,
                    created_by = CASE WHEN ? <> '' THEN ? ELSE created_by END,
                    note = CASE WHEN ? <> '' THEN ? ELSE note END
                WHERE id = ?
                """,
                (
                    assignment_id, owner_name, owner_name, primary,
                    created_by, created_by, note, note, access_id,
                ),
            )
            return access_id
        cursor = conn.execute(
            """
            INSERT INTO key_accesses(
                key_id, assignment_id, access_type, address, apartment,
                owner_name, active, is_primary, source, created_by, note
            ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
            RETURNING id
            """,
            (
                key_id, assignment_id, access_type, address, apartment,
                owner_name, int(primary), source, created_by, note,
            ),
        )
        return int(cursor.fetchone()[0])


def sync_primary_access(
    key_id: int,
    *,
    assignment_type: str,
    address: str,
    apartment: str = "",
    owner_name: str = "",
    assignment_id: int | None = None,
    created_by: str = "",
    note: str = "",
) -> int:
    """Synchronise the backwards-compatible primary assignment projection.

    This is deliberately separate from ``ensure_access``: editing owner
    metadata must replace the primary projection instead of accidentally
    leaving both the former resident/service row and the new row active.
    Additional non-primary accesses are preserved.
    """
    access_type = access_type_for_assignment(assignment_type)
    address = str(address or "").strip()
    apartment = str(apartment or "").strip()
    owner_name = str(owner_name or "").strip()
    created_by = str(created_by or "").strip()
    note = str(note or "").strip()

    with db() as conn:
        primary = conn.execute(
            """
            SELECT id FROM key_accesses
            WHERE key_id = ? AND active = 1 AND is_primary = 1
            ORDER BY id DESC LIMIT 1
            """,
            (key_id,),
        ).fetchone()
        matching = conn.execute(
            """
            SELECT id FROM key_accesses
            WHERE key_id = ? AND active = 1 AND access_type = ?
              AND address = ? AND apartment = ?
            ORDER BY is_primary DESC, id DESC LIMIT 1
            """,
            (key_id, access_type, address, apartment),
        ).fetchone()

        primary_id = int(primary[0]) if primary else None
        target_id = int(matching[0]) if matching else primary_id
        if target_id is None:
            row = conn.execute(
                """
                INSERT INTO key_accesses(
                    key_id, assignment_id, access_type, address, apartment,
                    owner_name, active, is_primary, source, created_by, note
                ) VALUES (?, ?, ?, ?, ?, ?, 1, 1, 'assignment_edit', ?, ?)
                RETURNING id
                """,
                (
                    key_id, assignment_id, access_type, address, apartment,
                    owner_name, created_by, note,
                ),
            ).fetchone()
            return int(row[0])

        if primary_id is not None and primary_id != target_id:
            conn.execute(
                """
                UPDATE key_accesses
                SET active = 0, is_primary = 0,
                    released_at = CURRENT_TIMESTAMP,
                    note = CASE WHEN ? <> '' THEN ? ELSE note END
                WHERE id = ?
                """,
                (note, note, primary_id),
            )
        conn.execute(
            "UPDATE key_accesses SET is_primary = 0 WHERE key_id = ? AND active = 1",
            (key_id,),
        )
        conn.execute(
            """
            UPDATE key_accesses
            SET assignment_id = COALESCE(?, assignment_id),
                access_type = ?, address = ?, apartment = ?,
                owner_name = ?, is_primary = 1,
                created_by = CASE WHEN ? <> '' THEN ? ELSE created_by END,
                note = CASE WHEN ? <> '' THEN ? ELSE note END
            WHERE id = ?
            """,
            (
                assignment_id, access_type, address, apartment, owner_name,
                created_by, created_by, note, note, target_id,
            ),
        )
        return target_id


def attach_panels(key_id: int, access_id: int, panel_ids: list[int]) -> None:
    clean_ids = sorted({int(value) for value in panel_ids if int(value) > 0})
    if not clean_ids:
        return
    placeholders = ",".join("?" for _ in clean_ids)
    with db() as conn:
        conn.execute(
            f"""
            UPDATE key_panel_states
            SET access_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE key_id = ? AND panel_id IN ({placeholders})
              AND state IN ('active', 'pending_write')
            """,
            [access_id, key_id, *clean_ids],
        )


def close_active_accesses(key_id: int, *, reason: str = "") -> None:
    with db() as conn:
        conn.execute(
            """
            UPDATE key_accesses
            SET active = 0, is_primary = 0, released_at = CURRENT_TIMESTAMP,
                note = CASE WHEN ? <> '' THEN ? ELSE note END
            WHERE key_id = ? AND active = 1
            """,
            (reason, reason, key_id),
        )


def close_accesses(key_id: int, access_ids: list[int], *, reason: str = "") -> None:
    clean_ids = sorted({int(value) for value in access_ids if int(value) > 0})
    if not clean_ids:
        return
    placeholders = ",".join("?" for _ in clean_ids)
    with db() as conn:
        conn.execute(
            f"""
            UPDATE key_accesses
            SET active = 0, is_primary = 0, released_at = CURRENT_TIMESTAMP,
                note = CASE WHEN ? <> '' THEN ? ELSE note END
            WHERE key_id = ? AND active = 1 AND id IN ({placeholders})
            """,
            [reason, reason, key_id, *clean_ids],
        )


def get_access_panels(access_id: int) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT kps.*, p.address, p.entrance, p.name AS panel_name, p.mac
            FROM key_panel_states kps
            JOIN panels p ON p.id = kps.panel_id
            WHERE kps.access_id = ?
              AND kps.state IN ('active', 'pending_delete')
            ORDER BY p.address, p.entrance, p.id
            """,
            (access_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def clone_snapshot_accesses(
    new_key_id: int,
    snapshot: dict,
    *,
    created_by: str = "",
    source: str = "replacement",
) -> dict[int, int]:
    """Rebuild the exact active access projection for a replacement key."""
    old_to_new: dict[int, int] = {}
    assignments = list(snapshot.get("assignments") or [])
    with db() as conn:
        row = conn.execute(
            "SELECT id FROM key_assignments WHERE key_id = ? AND active = 1 ORDER BY id DESC LIMIT 1",
            (new_key_id,),
        ).fetchone()
    primary_assignment_id = int(row[0]) if row else None

    for item in snapshot.get("accesses") or []:
        old_id = int(item["id"])
        new_id = ensure_access(
            new_key_id,
            assignment_type="resident" if item.get("access_type") == "resident" else "service",
            address=item.get("address") or "",
            apartment=item.get("apartment") or "",
            owner_name=item.get("owner_name") or "",
            assignment_id=primary_assignment_id if item.get("is_primary") else None,
            primary=bool(item.get("is_primary")),
            source=source,
            created_by=created_by,
            note=item.get("note") or "",
        )
        old_to_new[old_id] = new_id

    if not old_to_new and assignments:
        item = assignments[0]
        old_to_new[-1] = ensure_access(
            new_key_id,
            assignment_type=item.get("assignment_type") or "resident",
            address=item.get("address") or "",
            apartment=item.get("apartment") or "",
            owner_name=item.get("owner_name") or item.get("employee_name") or item.get("uk_name") or "",
            assignment_id=primary_assignment_id,
            primary=True,
            source=source,
            created_by=created_by,
            note=item.get("note") or "",
        )

    panels_by_access: dict[int, list[int]] = {}
    fallback_id = next(iter(old_to_new.values()), None)
    for panel in snapshot.get("panels") or []:
        old_access_id = panel.get("access_id")
        new_access_id = old_to_new.get(int(old_access_id)) if old_access_id else fallback_id
        if new_access_id:
            panels_by_access.setdefault(new_access_id, []).append(int(panel["panel_id"]))
    for access_id, panel_ids in panels_by_access.items():
        attach_panels(new_key_id, access_id, panel_ids)
    return old_to_new
