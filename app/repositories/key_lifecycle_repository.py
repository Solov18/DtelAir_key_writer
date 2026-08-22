"""Authoritative local state and durable key lifecycle operations.

`operation_log` is deliberately not read here: it is immutable audit history,
not a projection of what is currently programmed on a panel.
"""

import json

from app.db import db


def _json_dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _json_load(value: str, fallback):
    try:
        return json.loads(value or "")
    except (TypeError, ValueError):
        return fallback


def _assignment_signature(snapshot: dict) -> list[dict]:
    """Return the stable part of the active assignment for resume checks."""
    fields = (
        "id", "assignment_type", "address", "apartment", "employee_id",
        "uk_group_id", "owner_name", "note",
    )
    return [
        {field: item.get(field) for field in fields}
        for item in snapshot.get("assignments", [])
    ]


def _resume_context(snapshot: dict) -> dict:
    return {
        "scope": snapshot.get("_lifecycle_scope") or "release",
        "target": snapshot.get("_target_context") or {},
        "assignment": _assignment_signature(snapshot),
    }


def _can_resume_operation(conn, row, current_snapshot: dict) -> bool:
    """Resume only when the persisted job still describes current state.

    Successful delete steps are deliberately subtracted from the persisted
    source set.  This keeps a genuine partial operation resumable after a
    restart, while an obsolete operation for another panel/address is not
    accidentally reused.
    """
    saved_snapshot = _json_load(row["assignment_snapshot"], {})
    saved_context = _resume_context(saved_snapshot)
    current_context = _resume_context(current_snapshot)
    if (
        saved_context["scope"] != current_context["scope"]
        or saved_context["target"] != current_context["target"]
    ):
        return False

    source_ids = {
        int(value) for value in _json_load(row["source_panel_ids"], [])
    }
    completed_ids = {
        int(step["panel_id"])
        for step in conn.execute(
            """
            SELECT panel_id FROM key_lifecycle_steps
            WHERE operation_id = ? AND phase = 'delete_old' AND state = 'success'
            """,
            (row["id"],),
        ).fetchall()
    }
    # During replace the old key is finalized immediately after every old
    # panel was deleted.  A process restart may therefore see no active old
    # assignment while the persisted operation is still writing the new key.
    # That is the one valid case where the current assignment signature is
    # expected to differ from the pre-release snapshot.
    write_after_release = (
        row["operation_type"] in {"replace", "reassign"}
        and source_ids == completed_ids
        and row["status"] in {"writing", "partial", "error"}
    )
    if (
        not write_after_release
        and saved_context["assignment"] != current_context["assignment"]
    ):
        return False

    current_ids = {
        int(panel["panel_id"])
        for panel in current_snapshot.get("panels", [])
    }
    if write_after_release and row["operation_type"] == "reassign":
        completed_write_ids = {
            int(step["panel_id"])
            for step in conn.execute(
                """
                SELECT panel_id FROM key_lifecycle_steps
                WHERE operation_id = ? AND phase = 'write_new' AND state = 'success'
                """,
                (row["id"],),
            ).fetchall()
        }
        return current_ids == completed_write_ids

    expected_remaining = source_ids - completed_ids
    return current_ids == expected_remaining


def create_or_resume_operation(
    *, operation_type: str, old_key_id: int, new_key_id: int | None,
    reason: str, final_old_status: str, employee_assignment_status: str,
    snapshot: dict,
) -> dict:
    """Return the latest incomplete matching operation or persist a new one."""
    with db() as conn:
        row = conn.execute(
            """
            SELECT * FROM key_lifecycle_operations
            WHERE operation_type = ? AND old_key_id = ?
              AND COALESCE(new_key_id, 0) = COALESCE(?, 0)
              AND status <> 'completed'
            ORDER BY id DESC LIMIT 1
            """,
            (operation_type, old_key_id, new_key_id),
        ).fetchone()
        if row and not _can_resume_operation(conn, row, snapshot):
            conn.execute(
                """
                UPDATE key_lifecycle_operations
                SET status = 'completed',
                    last_error = 'Операция отменена: текущее назначение или набор панелей изменился',
                    completed_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (row["id"],),
            )
            row = None

        if not row:
            panel_ids = [int(panel["panel_id"]) for panel in snapshot.get("panels", [])]
            cursor = conn.execute(
                """
                INSERT INTO key_lifecycle_operations(
                    operation_type, status, old_key_id, new_key_id, reason,
                    final_old_status, employee_assignment_status,
                    source_panel_ids, assignment_snapshot, updated_at
                ) VALUES (?, 'pending', ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    operation_type, old_key_id, new_key_id, reason,
                    final_old_status, employee_assignment_status,
                    _json_dump(panel_ids), _json_dump(snapshot),
                ),
            )
            row = conn.execute(
                "SELECT * FROM key_lifecycle_operations WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
    result = dict(row)
    result["source_panel_ids"] = _json_load(result.get("source_panel_ids"), [])
    result["assignment_snapshot"] = _json_load(result.get("assignment_snapshot"), {})
    return result


def ensure_operation_steps(operation_id: int, panel_ids: list[int], phase: str) -> None:
    with db() as conn:
        for panel_id in panel_ids:
            conn.execute(
                """
                INSERT INTO key_lifecycle_steps(operation_id, panel_id, phase)
                VALUES (?, ?, ?)
                ON CONFLICT (operation_id, panel_id, phase) DO NOTHING
                """,
                (operation_id, int(panel_id), phase),
            )


def get_operation_steps(operation_id: int, phase: str | None = None) -> list[dict]:
    sql = "SELECT * FROM key_lifecycle_steps WHERE operation_id = ?"
    params: list = [operation_id]
    if phase:
        sql += " AND phase = ?"
        params.append(phase)
    sql += " ORDER BY id"
    with db() as conn:
        rows = conn.execute(sql, params).fetchall()
    items = [dict(row) for row in rows]
    for item in items:
        item["result_payload"] = _json_load(item.get("result_payload"), {})
    return items


def mark_step_running(step_id: int) -> None:
    with db() as conn:
        conn.execute(
            """
            UPDATE key_lifecycle_steps
            SET state = 'running', attempts = attempts + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND state <> 'success'
            """,
            (step_id,),
        )


def record_step_result(
    step_id: int, *, success: bool, status: str, error: str = "", payload=None,
) -> None:
    with db() as conn:
        conn.execute(
            """
            UPDATE key_lifecycle_steps
            SET state = ?, last_status = ?, last_error = ?, result_payload = ?,
                completed_at = CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                "success" if success else "error", status or "", error or "",
                _json_dump(payload or {}), success, step_id,
            ),
        )


def set_operation_status(operation_id: int, status: str, error: str = "") -> None:
    with db() as conn:
        conn.execute(
            """
            UPDATE key_lifecycle_operations
            SET status = ?, last_error = ?,
                completed_at = CASE WHEN ? = 'completed' THEN CURRENT_TIMESTAMP ELSE NULL END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (status, error or "", status, operation_id),
        )


def get_operation(operation_id: int) -> dict | None:
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM key_lifecycle_operations WHERE id = ?", (operation_id,)
        ).fetchone()
    if not row:
        return None
    result = dict(row)
    result["source_panel_ids"] = _json_load(result.get("source_panel_ids"), [])
    result["assignment_snapshot"] = _json_load(result.get("assignment_snapshot"), {})
    result["steps"] = get_operation_steps(operation_id)
    return result


def can_record_panel_state(key_id: int, panel_id: int) -> bool:
    """Guard synthetic/presentation calls that do not reference persisted rows."""
    with db() as conn:
        return bool(conn.execute(
            """SELECT 1 FROM keys k, panels p
               WHERE k.id = ? AND p.id = ? LIMIT 1""",
            (key_id, panel_id),
        ).fetchone())


def get_key_snapshot(key_id: int) -> dict | None:
    with db() as conn:
        key = conn.execute(
            """
            SELECT k.*, kt.name AS type_name
            FROM keys k
            JOIN key_types kt ON kt.id = k.key_type_id
            WHERE k.id = ?
            """,
            (key_id,),
        ).fetchone()
        if not key:
            return None
        assignments = conn.execute(
            """
            SELECT ka.*, e.full_name AS employee_name, ug.name AS uk_name
            FROM key_assignments ka
            LEFT JOIN employees e ON e.id = ka.employee_id
            LEFT JOIN uk_groups ug ON ug.id = ka.uk_group_id
            WHERE ka.key_id = ? AND ka.active = 1
            ORDER BY ka.id DESC
            """,
            (key_id,),
        ).fetchall()
        accesses = conn.execute(
            """
            SELECT * FROM key_accesses
            WHERE key_id = ? AND active = 1
            ORDER BY is_primary DESC, assigned_at, id
            """,
            (key_id,),
        ).fetchall()
        panels = conn.execute(
            """
            SELECT kps.*, p.address, p.entrance, p.name AS panel_name, p.mac,
                   ka.address AS access_address,
                   ka.apartment AS access_apartment,
                   ka.access_type
            FROM key_panel_states kps
            JOIN panels p ON p.id = kps.panel_id
            LEFT JOIN key_accesses ka ON ka.id = kps.access_id
            WHERE kps.key_id = ?
              AND (
                  kps.state IN ('active', 'pending_delete')
                  OR (kps.state = 'error' AND kps.last_operation = 'delete')
              )
            ORDER BY p.address, p.entrance, p.name, p.id
            """,
            (key_id,),
        ).fetchall()
        employee_active = conn.execute(
            "SELECT 1 FROM employee_keys WHERE key_id = ? AND status = 'active' LIMIT 1",
            (key_id,),
        ).fetchone()
        uk_active = conn.execute(
            """
            SELECT 1 FROM uk_key_issues
            WHERE key_id = ? AND status IN ('pending', 'active') LIMIT 1
            """,
            (key_id,),
        ).fetchone()

    item = dict(key)
    item["assignments"] = [dict(row) for row in assignments]
    item["accesses"] = [dict(row) for row in accesses]
    item["panels"] = [dict(row) for row in panels]
    item["occupied"] = bool(
        item["assignments"]
        or item["accesses"]
        or item["panels"]
        or employee_active
        or uk_active
        or item.get("status") not in {"", "free"}
    )
    return item


def record_panel_result(
    *,
    key_id: int,
    panel_id: int,
    operation: str,
    status: str,
    success: bool,
    flat_num: str = "0",
    inner: int = 1,
    uk_group_id: int | None = None,
    error: str = "",
) -> None:
    normalized_operation = "delete" if operation == "delete" else "write"
    if normalized_operation == "write":
        state = "active" if success else "error"
    else:
        state = "removed" if success else "error"
    with db() as conn:
        conn.execute(
            """
            INSERT INTO key_panel_states(
                key_id, panel_id, state, flat_num, is_inner, uk_group_id,
                last_operation, last_status, last_error,
                confirmed_at, removed_at, updated_at
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?,
                CASE WHEN ? AND ? = 'write' THEN CURRENT_TIMESTAMP ELSE NULL END,
                CASE WHEN ? AND ? = 'delete' THEN CURRENT_TIMESTAMP ELSE NULL END,
                CURRENT_TIMESTAMP
            )
            ON CONFLICT (key_id, panel_id) DO UPDATE SET
                state = EXCLUDED.state,
                flat_num = EXCLUDED.flat_num,
                is_inner = EXCLUDED.is_inner,
                uk_group_id = COALESCE(EXCLUDED.uk_group_id, key_panel_states.uk_group_id),
                last_operation = EXCLUDED.last_operation,
                last_status = EXCLUDED.last_status,
                last_error = EXCLUDED.last_error,
                confirmed_at = CASE
                    WHEN EXCLUDED.state = 'active' THEN CURRENT_TIMESTAMP
                    ELSE key_panel_states.confirmed_at
                END,
                removed_at = CASE
                    WHEN EXCLUDED.state = 'removed' THEN CURRENT_TIMESTAMP
                    ELSE NULL
                END,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                key_id, panel_id, state, str(flat_num or "0"), int(inner),
                uk_group_id, normalized_operation, status or "", error or "",
                success, normalized_operation, success, normalized_operation,
            ),
        )


def mark_panels_pending_delete(key_id: int, panel_ids: list[int]) -> None:
    if not panel_ids:
        return
    placeholders = ",".join("?" for _ in panel_ids)
    with db() as conn:
        conn.execute(
            f"""
            UPDATE key_panel_states
            SET state = 'pending_delete', last_operation = 'delete',
                last_error = '', updated_at = CURRENT_TIMESTAMP
            WHERE key_id = ? AND panel_id IN ({placeholders})
              AND (
                  state IN ('active', 'pending_delete')
                  OR (state = 'error' AND last_operation = 'delete')
              )
            """,
            [key_id, *panel_ids],
        )


def finalize_release(
    key_id: int, *, final_status: str, reason: str,
    employee_assignment_status: str = "inactive",
) -> None:
    with db() as conn:
        remaining = conn.execute(
            """
            SELECT 1 FROM key_panel_states
            WHERE key_id = ?
              AND (
                  state IN ('active', 'pending_delete')
                  OR (state = 'error' AND last_operation = 'delete')
              )
            LIMIT 1
            """,
            (key_id,),
        ).fetchone()
        if remaining:
            raise ValueError("Не все панели подтверждённо освободили ключ.")
        conn.execute(
            """
            UPDATE employee_keys
            SET status = ?, closed_at = CURRENT_TIMESTAMP,
                close_reason = CASE WHEN ? <> '' THEN ? ELSE 'Ключ освобождён' END,
                updated_at = CURRENT_TIMESTAMP
            WHERE key_id = ? AND status = 'active'
            """,
            (employee_assignment_status, reason, reason, key_id),
        )
        conn.execute(
            """
            UPDATE key_assignments
            SET active = 0, released_at = CURRENT_TIMESTAMP,
                note = CASE WHEN ? <> '' THEN ? ELSE note END
            WHERE key_id = ? AND active = 1
            """,
            (reason, reason, key_id),
        )
        conn.execute(
            """
            UPDATE key_accesses
            SET active = 0, is_primary = 0, released_at = CURRENT_TIMESTAMP,
                note = CASE WHEN ? <> '' THEN ? ELSE note END
            WHERE key_id = ? AND active = 1
            """,
            (reason, reason, key_id),
        )
        conn.execute(
            """
            UPDATE uk_key_issues
            SET status = 'released', released_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE key_id = ? AND status IN ('pending', 'active')
            """,
            (key_id,),
        )
        conn.execute(
            """
            UPDATE uk_key_programmings
            SET active = FALSE, status = 'removed', removed_at = COALESCE(removed_at, CURRENT_TIMESTAMP),
                updated_at = CURRENT_TIMESTAMP
            WHERE issue_id IN (SELECT id FROM uk_key_issues WHERE key_id = ?)
              AND active = TRUE
            """,
            (key_id,),
        )
        cursor = conn.execute(
            """
            UPDATE keys
            SET status = ?, is_used = 0,
                note = CASE WHEN ? <> '' THEN ? ELSE note END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (final_status, reason, reason, key_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("Ключ не найден.")
