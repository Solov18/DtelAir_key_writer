from app.db import db
from app.services.auth import hash_password


def main(action: str) -> None:
    with db() as conn:
        context = dict(
            conn.execute(
                "SELECT current_database() AS database, current_schema() AS schema"
            ).fetchone()
        )
        if context["database"] != "key_writer_test":
            raise RuntimeError(f"Unsafe visual database: {context}")
        conn.execute("DELETE FROM users WHERE login = ?", ("codex_visual_uk",))
        if action == "create":
            role = conn.execute(
                "SELECT id FROM roles WHERE code = ?", ("admin",)
            ).fetchone()
            conn.execute(
                """
                INSERT INTO users(full_name, login, password_hash, role_id, active)
                VALUES (?, ?, ?, ?, 1)
                """,
                (
                    "Визуальная проверка",
                    "codex_visual_uk",
                    hash_password("Visual-Only-4827"),
                    int(role["id"]),
                ),
            )
        print(f"VISUAL_USER_{action.upper()} database={context['database']} schema={context['schema']}")


if __name__ == "__main__":
    import sys

    main(sys.argv[1])
