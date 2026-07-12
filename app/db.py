import sqlite3
from contextlib import contextmanager
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

DB_PATH = DATA_DIR / "app.db"


@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _add_column_if_missing(
    conn: sqlite3.Connection,
    table_name: str,
    column_name: str,
    column_sql: str,
) -> None:
    columns = {
        row["name"]
        for row in conn.execute(
            f"PRAGMA table_info({table_name})"
        ).fetchall()
    }

    if column_name not in columns:
        conn.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_sql}"
        )


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
        """,
        (table_name,),
    ).fetchone()

    return row is not None


def _get_table_columns(
    conn: sqlite3.Connection,
    table_name: str,
) -> set[str]:
    return {
        row["name"]
        for row in conn.execute(
            f"PRAGMA table_info({table_name})"
        ).fetchall()
    }


def _create_employee_keys_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE employee_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            key_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            issued_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            closed_at TEXT DEFAULT NULL,
            close_reason TEXT DEFAULT '',
            comment TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(employee_id, key_id),
            FOREIGN KEY(employee_id)
                REFERENCES employees(id)
                ON DELETE RESTRICT,
            FOREIGN KEY(key_id)
                REFERENCES keys(id)
                ON DELETE RESTRICT
        )
        """
    )


def _migrate_employee_keys(conn: sqlite3.Connection) -> None:
    """Безопасно обновляет старую таблицу employee_keys, сохраняя данные."""
    if not _table_exists(conn, "employee_keys"):
        _create_employee_keys_table(conn)
        return

    columns = _get_table_columns(conn, "employee_keys")
    required_columns = {
        "id",
        "employee_id",
        "key_id",
        "status",
        "issued_at",
        "closed_at",
        "close_reason",
        "comment",
        "created_at",
        "updated_at",
    }

    if required_columns.issubset(columns):
        return

    old_rows = conn.execute(
        """
        SELECT
            employee_id,
            key_id,
            COALESCE(created_at, CURRENT_TIMESTAMP) AS created_at
        FROM employee_keys
        ORDER BY
            employee_id,
            datetime(COALESCE(created_at, CURRENT_TIMESTAMP)) DESC,
            key_id DESC
        """
    ).fetchall()

    conn.execute("ALTER TABLE employee_keys RENAME TO employee_keys_old")
    _create_employee_keys_table(conn)

    active_employee_ids: set[int] = set()
    active_key_ids: set[int] = set()

    for row in old_rows:
        employee_id = int(row["employee_id"])
        key_id = int(row["key_id"])
        created_at = row["created_at"]

        can_be_active = (
            employee_id not in active_employee_ids
            and key_id not in active_key_ids
        )

        if can_be_active:
            status = "active"
            closed_at = None
            close_reason = ""
            active_employee_ids.add(employee_id)
            active_key_ids.add(key_id)
        else:
            status = "replaced"
            closed_at = created_at
            close_reason = "Перенесён из старой структуры"

        conn.execute(
            """
            INSERT OR IGNORE INTO employee_keys(
                employee_id,
                key_id,
                status,
                issued_at,
                closed_at,
                close_reason,
                comment,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, '', ?, ?)
            """,
            (
                employee_id,
                key_id,
                status,
                created_at,
                closed_at,
                close_reason,
                created_at,
                created_at,
            ),
        )

    conn.execute("DROP TABLE employee_keys_old")


def _create_employee_key_indexes(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS
            idx_employee_keys_one_active_per_employee
        ON employee_keys(employee_id)
        WHERE status = 'active'
        """
    )

    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS
            idx_employee_keys_one_active_employee_per_key
        ON employee_keys(key_id)
        WHERE status = 'active'
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS
            idx_employee_keys_employee_history
        ON employee_keys(employee_id, status, issued_at)
        """
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

            CREATE TABLE IF NOT EXISTS uk_group_keys (
                group_id INTEGER NOT NULL,
                key_id INTEGER NOT NULL,
                UNIQUE(group_id, key_id)
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

        # Изменения только для учёта сотрудников и истории ключей.
        _add_column_if_missing(
            conn,
            "employees",
            "updated_at",
            "updated_at TEXT DEFAULT ''",
        )
        _add_column_if_missing(
            conn,
            "employees",
            "dismissed_at",
            "dismissed_at TEXT DEFAULT NULL",
        )
        _migrate_employee_keys(conn)
        _create_employee_key_indexes(conn)

        _add_column_if_missing(
            conn,
            "uk_groups",
            "crm_login",
            "crm_login TEXT DEFAULT ''",
        )
        _add_column_if_missing(
            conn,
            "uk_groups",
            "crm_password",
            "crm_password TEXT DEFAULT ''",
        )

        # Обновление старой таблицы operation_log, если база создана раньше.
        operation_log_columns = {
            "action": "action TEXT DEFAULT ''",
            "object_type": "object_type TEXT DEFAULT ''",
            "object_name": "object_name TEXT DEFAULT ''",
            "details": "details TEXT DEFAULT ''",
            "address": "address TEXT DEFAULT ''",
            "apartment": "apartment TEXT DEFAULT ''",
            "username": "username TEXT DEFAULT ''",
            "user_full_name": "user_full_name TEXT DEFAULT ''",
            "user_role": "user_role TEXT DEFAULT ''",
            "ip_address": "ip_address TEXT DEFAULT ''",
        }

        for column_name, column_sql in operation_log_columns.items():
            _add_column_if_missing(
                conn,
                "operation_log",
                column_name,
                column_sql,
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
