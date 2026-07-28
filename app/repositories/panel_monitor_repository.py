"""Persistent coordination state for the centralized panel monitor."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from app.db import db


STATE_ID = 1


def _as_dict(row) -> dict:
    if row is None:
        return {
            "id": STATE_ID,
            "status": "idle",
            "total": 0,
            "completed": 0,
            "online": 0,
            "failed": 0,
            "active_panel_ids": [],
        }
    result = dict(row)
    result["active_panel_ids"] = list(result.get("active_panel_ids") or [])
    for key in ("total", "completed", "online", "failed"):
        result[key] = int(result.get(key) or 0)
    return result


def ensure_monitor_state() -> None:
    with db() as conn:
        conn.execute(
            """
            INSERT INTO panel_monitor_state(id, status)
            VALUES (?, 'idle')
            ON CONFLICT (id) DO NOTHING
            """,
            (STATE_ID,),
        )


def get_monitor_state() -> dict:
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM panel_monitor_state WHERE id = ?",
            (STATE_ID,),
        ).fetchone()
    return _as_dict(row)


def request_monitor_cycle(requested_by: str = "") -> tuple[dict, bool]:
    """Queue one shared cycle, or return the already queued/running cycle."""

    ensure_monitor_state()
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM panel_monitor_state WHERE id = ? FOR UPDATE",
            (STATE_ID,),
        ).fetchone()
        state = _as_dict(row)
        if state["status"] in {"queued", "running"}:
            return state, False
        row = conn.execute(
            """
            UPDATE panel_monitor_state
            SET status = 'queued',
                requested_at = CURRENT_TIMESTAMP,
                requested_by = ?,
                last_error = ''
            WHERE id = ?
            RETURNING *
            """,
            ((requested_by or "")[:200], STATE_ID),
        ).fetchone()
    return _as_dict(row), True


def begin_cycle_if_due(interval_seconds: int) -> dict | None:
    """Atomically claim a queued or scheduled cycle for the elected worker."""

    ensure_monitor_state()
    interval_seconds = max(30, int(interval_seconds))
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM panel_monitor_state WHERE id = ? FOR UPDATE",
            (STATE_ID,),
        ).fetchone()
        state = _as_dict(row)
        due = (
            state["status"] == "queued"
            or (
                state["status"] in {"idle", "completed", "failed"}
                and (
                    state.get("finished_at") is None
                    or (
                        datetime.now(timezone.utc) - state["finished_at"]
                    ).total_seconds()
                    >= interval_seconds
                )
            )
        )
        if not due:
            return None
        row = conn.execute(
            """
            UPDATE panel_monitor_state
            SET status = 'running',
                total = 0,
                completed = 0,
                online = 0,
                failed = 0,
                active_panel_ids = '[]'::jsonb,
                started_at = CURRENT_TIMESTAMP,
                finished_at = NULL,
                heartbeat_at = CURRENT_TIMESTAMP,
                last_error = ''
            WHERE id = ?
            RETURNING *
            """,
            (STATE_ID,),
        ).fetchone()
    return _as_dict(row)


def recover_interrupted_cycle(stale_after_seconds: int) -> bool:
    """Requeue a run abandoned by a process that lost the advisory lock."""

    stale_after_seconds = max(30, int(stale_after_seconds))
    with db() as conn:
        cursor = conn.execute(
            """
            UPDATE panel_monitor_state
            SET status = 'queued',
                active_panel_ids = '[]'::jsonb,
                last_error = 'Предыдущий процесс мониторинга был прерван; цикл запущен повторно'
            WHERE id = ?
              AND status = 'running'
              AND (
                    heartbeat_at IS NULL
                    OR heartbeat_at < CURRENT_TIMESTAMP - (? * INTERVAL '1 second')
              )
            """,
            (STATE_ID, stale_after_seconds),
        )
    return cursor.rowcount > 0


def set_cycle_total(total: int) -> None:
    with db() as conn:
        conn.execute(
            """
            UPDATE panel_monitor_state
            SET total = ?, heartbeat_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (max(0, int(total)), STATE_ID),
        )


def update_cycle_progress(
    *,
    completed: int,
    online: int,
    failed: int,
    active_panel_ids: list[int],
) -> None:
    with db() as conn:
        conn.execute(
            """
            UPDATE panel_monitor_state
            SET completed = ?,
                online = ?,
                failed = ?,
                active_panel_ids = CAST(? AS jsonb),
                heartbeat_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = 'running'
            """,
            (
                max(0, int(completed)),
                max(0, int(online)),
                max(0, int(failed)),
                json.dumps(sorted({int(value) for value in active_panel_ids})),
                STATE_ID,
            ),
        )


def finish_cycle(*, completed: int, online: int, failed: int, error: str = "") -> None:
    status = "failed" if error and completed == 0 else "completed"
    with db() as conn:
        conn.execute(
            """
            UPDATE panel_monitor_state
            SET status = ?,
                completed = ?,
                online = ?,
                failed = ?,
                active_panel_ids = '[]'::jsonb,
                finished_at = CURRENT_TIMESTAMP,
                heartbeat_at = CURRENT_TIMESTAMP,
                last_error = ?
            WHERE id = ?
            """,
            (
                status,
                max(0, int(completed)),
                max(0, int(online)),
                max(0, int(failed)),
                (error or "")[:1000],
                STATE_ID,
            ),
        )

