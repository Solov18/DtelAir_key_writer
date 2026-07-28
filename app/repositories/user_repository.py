from app.db import db


_USER_SELECT = """
    SELECT
        u.id,
        u.full_name,
        u.login,
        u.password_hash,
        u.role_id,
        u.active,
        u.created_at,
        u.last_login,
        r.code AS role,
        r.name AS role_name,
        COALESCE(
            ARRAY_AGG(DISTINCT p.code) FILTER (WHERE p.code IS NOT NULL),
            ARRAY[]::TEXT[]
        ) AS permissions
    FROM users u
    JOIN roles r ON r.id = u.role_id
    LEFT JOIN role_permissions rp ON rp.role_id = r.id
    LEFT JOIN permissions p ON p.id = rp.permission_id
"""


def _user_from_row(row) -> dict | None:
    if not row:
        return None
    item = dict(row)
    item["permissions"] = set(item.get("permissions") or [])
    return item


def get_user_by_login(login: str) -> dict | None:
    with db() as conn:
        row = conn.execute(
            _USER_SELECT
            + """
            WHERE LOWER(u.login) = LOWER(?)
            GROUP BY u.id, r.id
            """,
            (login.strip(),),
        ).fetchone()
    return _user_from_row(row)


def get_user_by_id(user_id: int) -> dict | None:
    with db() as conn:
        row = conn.execute(
            _USER_SELECT
            + """
            WHERE u.id = ?
            GROUP BY u.id, r.id
            """,
            (user_id,),
        ).fetchone()
    return _user_from_row(row)


def update_last_login(user_id: int) -> None:
    with db() as conn:
        conn.execute(
            "UPDATE users SET last_login = CAST(CURRENT_TIMESTAMP AS TEXT) WHERE id = ?",
            (user_id,),
        )


def get_users() -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            _USER_SELECT
            + """
            GROUP BY u.id, r.id
            ORDER BY u.active DESC, u.full_name
            """
        ).fetchall()
    return [_user_from_row(row) for row in rows]


def _role_id_for_code(conn, role: str) -> int:
    row = conn.execute("SELECT id FROM roles WHERE code = ?", (role,)).fetchone()
    if not row:
        raise ValueError("Роль не найдена")
    return int(row[0])


def create_user(full_name: str, login: str, password_hash: str, role: str):
    with db() as conn:
        role_id = _role_id_for_code(conn, role)
        return conn.execute(
            """
            INSERT INTO users(full_name, login, password_hash, role_id)
            VALUES (?, ?, ?, ?)
            """,
            (full_name.strip(), login.strip(), password_hash, role_id),
        ).lastrowid


def update_user(user_id: int, full_name: str, login: str, role_id: int) -> None:
    with db() as conn:
        conn.execute(
            """
            UPDATE users
            SET full_name = ?, login = ?, role_id = ?
            WHERE id = ?
            """,
            (full_name.strip(), login.strip(), role_id, user_id),
        )


def change_user_password(user_id: int, password_hash: str):
    with db() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (password_hash, user_id),
        )


def delete_user(user_id: int) -> None:
    with db() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))


def count_admins() -> int:
    with db() as conn:
        return int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM users u
                JOIN roles r ON r.id = u.role_id
                WHERE r.code = 'admin' AND u.active = 1
                """
            ).fetchone()[0]
        )


def update_user_role(user_id: int, role: str) -> None:
    with db() as conn:
        role_id = _role_id_for_code(conn, role)
        conn.execute("UPDATE users SET role_id = ? WHERE id = ?", (role_id, user_id))


def set_user_active(user_id: int, active: bool) -> None:
    with db() as conn:
        conn.execute(
            "UPDATE users SET active = ? WHERE id = ?",
            (1 if active else 0, user_id),
        )


def get_user_stats() -> dict:
    with db() as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE u.active = 1) AS active,
                COUNT(*) FILTER (WHERE r.code = 'admin' AND u.active = 1) AS admins,
                COUNT(*) FILTER (WHERE r.code = 'operator' AND u.active = 1) AS operators,
                COUNT(*) FILTER (WHERE r.code = 'viewer' AND u.active = 1) AS viewers
            FROM users u
            JOIN roles r ON r.id = u.role_id
            """
        ).fetchone()
    return {key: int(row[key] or 0) for key in row.keys()}
