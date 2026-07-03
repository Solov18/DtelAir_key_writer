from app.db import db


def get_user_by_login(login: str) -> dict | None:
    with db() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM users
            WHERE login = ?
              AND active = 1
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
              AND active = 1
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


def disable_user(user_id: int):
    with db() as conn:
        conn.execute(
            """
            UPDATE users
            SET active = 0
            WHERE id = ?
            """,
            (user_id,),
        )


def enable_user(user_id: int):
    with db() as conn:
        conn.execute(
            """
            UPDATE users
            SET active = 1
            WHERE id = ?
            """,
            (user_id,),
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