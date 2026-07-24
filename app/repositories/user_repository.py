from app.db import db


def get_user_by_login(login: str) -> dict | None:
    with db() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM users
            WHERE login = ?
            """,
            (login.strip(),),
        ).fetchone()

        return dict(row) if row else None


def get_user_by_id(user_id: int) -> dict | None:
    with db() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM users
            WHERE id = ?
              
            """,
            (user_id,),
        ).fetchone()

        return dict(row) if row else None


def update_last_login(user_id: int) -> None:
    with db() as conn:
        conn.execute(
            """
            UPDATE users
            SET last_login = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (user_id,),

        )

def get_users() -> list[dict]:
    with db() as conn:
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT
                    id,
                    full_name,
                    login,
                    role,
                    active,
                    created_at,
                    last_login
                FROM users
                ORDER BY active DESC, full_name
                """
            )
        ]


def create_user(
    full_name: str,
    login: str,
    password_hash: str,
    role: str,
):
    with db() as conn:
        conn.execute(
            """
            INSERT INTO users(
                full_name,
                login,
                password_hash,
                role
            )
            VALUES (?,?,?,?)
            """,
            (
                full_name.strip(),
                login.strip(),
                password_hash,
                role,
            ),
        )




def change_user_password(user_id: int, password_hash: str):
    with db() as conn:
        conn.execute(
            """
            UPDATE users
            SET password_hash = ?
            WHERE id = ?
            """,
            (
                password_hash,
                user_id,
            ),
        )

def delete_user(user_id: int) -> None:
    with db() as conn:
        conn.execute(
            """
            DELETE FROM users
            WHERE id = ?
            """,
            (user_id,),
        )


def count_admins() -> int:
    with db() as conn:
        return conn.execute(
            """
            SELECT COUNT(*)
            FROM users
            WHERE role='admin' AND active = 1
            """
        ).fetchone()[0]


def update_user_role(user_id: int, role: str) -> None:
    with db() as conn:
        conn.execute(
            "UPDATE users SET role = ? WHERE id = ?",
            (role, user_id),
        )


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
                SUM(CASE WHEN active = 1 THEN 1 ELSE 0 END) AS active,
                SUM(CASE WHEN role = 'admin' AND active = 1 THEN 1 ELSE 0 END) AS admins,
                SUM(CASE WHEN role = 'operator' AND active = 1 THEN 1 ELSE 0 END) AS operators,
                SUM(CASE WHEN role = 'viewer' AND active = 1 THEN 1 ELSE 0 END) AS viewers
            FROM users
            """
        ).fetchone()
        return {key: int(row[key] or 0) for key in row.keys()}
