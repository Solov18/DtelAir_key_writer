import sqlite3
from pathlib import Path
from contextlib import contextmanager

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

DB_PATH = DATA_DIR / "app.db"


@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _add_column_if_missing(conn, table_name: str, column_name: str, column_sql: str):
    columns = [
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    ]

    if column_name not in columns:
        conn.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_sql}"
        )


def init_db():
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                number TEXT UNIQUE NOT NULL,
                hex_value TEXT NOT NULL,
                key_type TEXT DEFAULT '',
                note TEXT DEFAULT '',
                is_used INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                note TEXT DEFAULT '',
                enabled INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                login TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'operator',
                active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_login TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS panels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                address TEXT NOT NULL,
                entrance TEXT DEFAULT '',
                name TEXT NOT NULL,
                mac TEXT UNIQUE NOT NULL,
                tags TEXT DEFAULT '',
                enabled INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS uk_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                note TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS uk_group_panels (
                group_id INTEGER NOT NULL,
                panel_id INTEGER NOT NULL,
                UNIQUE(group_id, panel_id)
            );

            CREATE TABLE IF NOT EXISTS operation_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                mode TEXT NOT NULL DEFAULT '',
                action TEXT DEFAULT '',
                object_type TEXT DEFAULT '',
                object_name TEXT DEFAULT '',
                details TEXT DEFAULT '',

                printed_number TEXT DEFAULT '',
                hex_value TEXT DEFAULT '',
                flat_num TEXT DEFAULT '',
                mac TEXT DEFAULT '',
                panel_name TEXT DEFAULT '',

                address TEXT DEFAULT '',
                apartment TEXT DEFAULT '',

                status TEXT NOT NULL DEFAULT 'success',
                response TEXT DEFAULT '',

                username TEXT DEFAULT '',
                user_full_name TEXT DEFAULT '',
                user_role TEXT DEFAULT '',
                ip_address TEXT DEFAULT '',

                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

        # Обновление старой таблицы operation_log, если база уже была создана раньше
        _add_column_if_missing(
            conn,
            "operation_log",
            "action",
            "action TEXT DEFAULT ''",
        )

        _add_column_if_missing(
            conn,
            "operation_log",
            "object_type",
            "object_type TEXT DEFAULT ''",
        )

        _add_column_if_missing(
            conn,
            "operation_log",
            "object_name",
            "object_name TEXT DEFAULT ''",
        )

        _add_column_if_missing(
            conn,
            "operation_log",
            "details",
            "details TEXT DEFAULT ''",
        )

        _add_column_if_missing(
            conn,
            "operation_log",
            "address",
            "address TEXT DEFAULT ''",
        )

        _add_column_if_missing(
            conn,
            "operation_log",
            "apartment",
            "apartment TEXT DEFAULT ''",
        )

        _add_column_if_missing(
            conn,
            "operation_log",
            "username",
            "username TEXT DEFAULT ''",
        )

        _add_column_if_missing(
            conn,
            "operation_log",
            "user_full_name",
            "user_full_name TEXT DEFAULT ''",
        )

        _add_column_if_missing(
            conn,
            "operation_log",
            "user_role",
            "user_role TEXT DEFAULT ''",
        )

        _add_column_if_missing(
            conn,
            "operation_log",
            "ip_address",
            "ip_address TEXT DEFAULT ''",
        )

        user_count = conn.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0]

        if user_count == 0:
            conn.execute(
                """
                INSERT INTO users(
                    full_name,
                    login,
                    password_hash,
                    role
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    "Главный администратор",
                    "admin",
                    "admin",
                    "admin",
                ),
            )