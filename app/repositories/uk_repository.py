from app.db import db


def get_groups():
    with db() as conn:
        return [dict(r) for r in conn.execute("""
            SELECT
                g.*,
                (SELECT COUNT(*) FROM uk_group_panels gp WHERE gp.group_id = g.id) AS panels_count,
                (SELECT COUNT(*) FROM uk_group_keys gk WHERE gk.group_id = g.id) AS keys_count
            FROM uk_groups g
            ORDER BY g.name
        """)]


def get_group(group_id: int):
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM uk_groups WHERE id = ?",
            (group_id,),
        ).fetchone()

        return dict(row) if row else None


def save_group(name: str, note: str = ""):
    with db() as conn:
        conn.execute("""
            INSERT INTO uk_groups(name, note)
            VALUES(?, ?)
            ON CONFLICT(name)
            DO UPDATE SET note = excluded.note
        """, (name.strip(), note.strip()))


def get_group_panels(group_id: int):
    with db() as conn:
        return [dict(r) for r in conn.execute("""
            SELECT p.*
            FROM panels p
            JOIN uk_group_panels gp ON gp.panel_id = p.id
            WHERE gp.group_id = ?
            ORDER BY p.address, p.entrance, p.name
        """, (group_id,))]


def get_available_panels(group_id: int):
    with db() as conn:
        return [dict(r) for r in conn.execute("""
            SELECT *
            FROM panels
            WHERE enabled = 1
              AND id NOT IN (
                  SELECT panel_id
                  FROM uk_group_panels
                  WHERE group_id = ?
              )
            ORDER BY address, entrance, name
        """, (group_id,))]


def add_panels(group_id: int, panel_ids: list[int]):
    with db() as conn:
        conn.executemany("""
            INSERT OR IGNORE INTO uk_group_panels(group_id, panel_id)
            VALUES(?, ?)
        """, [(group_id, int(pid)) for pid in panel_ids])


def remove_panel(group_id: int, panel_id: int):
    with db() as conn:
        conn.execute("""
            DELETE FROM uk_group_panels
            WHERE group_id = ? AND panel_id = ?
        """, (group_id, panel_id))


def get_group_keys(group_id: int):
    with db() as conn:
        return [dict(r) for r in conn.execute("""
            SELECT k.*
            FROM keys k
            JOIN uk_group_keys gk ON gk.key_id = k.id
            WHERE gk.group_id = ?
            ORDER BY k.number
        """, (group_id,))]


def add_keys(group_id: int, key_numbers: list[str]):
    added = []
    not_found = []

    with db() as conn:
        for number in key_numbers:
            key = conn.execute(
                "SELECT * FROM keys WHERE number = ? LIMIT 1",
                (number,),
            ).fetchone()

            if not key:
                not_found.append(number)
                continue

            conn.execute("""
                INSERT OR IGNORE INTO uk_group_keys(group_id, key_id)
                VALUES(?, ?)
            """, (group_id, key["id"]))

            added.append(dict(key))

    return {
        "added": added,
        "not_found": not_found,
    }


def remove_key(group_id: int, key_id: int):
    with db() as conn:
        conn.execute("""
            DELETE FROM uk_group_keys
            WHERE group_id = ? AND key_id = ?
        """, (group_id, key_id))

def delete_group(group_id: int):
    with db() as conn:
        conn.execute(
            "DELETE FROM uk_group_panels WHERE group_id=?",
            (group_id,),
        )

        conn.execute(
            "DELETE FROM uk_group_keys WHERE group_id=?",
            (group_id,),
        )

        conn.execute(
            "DELETE FROM uk_groups WHERE id=?",
            (group_id,),
        )