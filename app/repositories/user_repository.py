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