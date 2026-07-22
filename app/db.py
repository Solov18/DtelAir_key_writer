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


def _create_keys_v2_table(
    conn: sqlite3.Connection,
    table_name: str = "keys",
) -> None:
    conn.execute(
        f"""
        CREATE TABLE {table_name} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key_type_id INTEGER NOT NULL,
            number TEXT NOT NULL,
            hex_value TEXT NOT NULL DEFAULT '',
            key_type TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'free',
            note TEXT DEFAULT '',
            is_used INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            created_by TEXT DEFAULT '',
            FOREIGN KEY(key_type_id)
                REFERENCES key_types(id)
                ON DELETE RESTRICT
        )
        """
    )


def _ensure_default_key_type(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT id FROM key_types WHERE name = ? COLLATE NOCASE",
        ("Без типа",),
    ).fetchone()

    if row:
        return int(row["id"])

    cursor = conn.execute(
        """
        INSERT INTO key_types(name, color, note, enabled)
        VALUES (?, ?, ?, 1)
        """,
        (
            "Без типа",
            "#2A9DF4",
            "Тип для ключей, перенесённых из старой базы",
        ),
    )
    return int(cursor.lastrowid)


def _create_key_indexes(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_keys_type_number
        ON keys(key_type_id, number COLLATE NOCASE)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_keys_hex_lookup
        ON keys(hex_value COLLATE NOCASE)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_keys_status
        ON keys(status, key_type_id)
        """
    )


def _migrate_keys_inventory(conn: sqlite3.Connection) -> None:
    """Переносит старую таблицу keys в учёт по типу без потери ID."""
    columns = _get_table_columns(conn, "keys")

    if "key_type_id" in columns and "status" in columns:
        default_type_id = _ensure_default_key_type(conn)
        conn.execute(
            """
            UPDATE keys
            SET key_type_id = ?,
                key_type = 'Без типа'
            WHERE key_type_id IS NULL
            """,
            (default_type_id,),
        )
        _create_key_indexes(conn)
        return

    default_type_id = _ensure_default_key_type(conn)
    legacy_types = conn.execute(
        """
        SELECT DISTINCT TRIM(COALESCE(key_type, '')) AS name
        FROM keys
        WHERE TRIM(COALESCE(key_type, '')) <> ''
        """
    ).fetchall()

    for row in legacy_types:
        conn.execute(
            """
            INSERT OR IGNORE INTO key_types(name, color, note, enabled)
            VALUES (?, '#2A9DF4', 'Перенесено из старой базы', 1)
            """,
            (row["name"],),
        )

    type_ids = {
        row["name"].strip().lower(): int(row["id"])
        for row in conn.execute("SELECT id, name FROM key_types")
    }

    legacy_rows = conn.execute(
        """
        SELECT
            id,
            number,
            hex_value,
            COALESCE(key_type, '') AS key_type,
            COALESCE(note, '') AS note,
            COALESCE(is_used, 0) AS is_used,
            COALESCE(created_at, CURRENT_TIMESTAMP) AS created_at,
            COALESCE(updated_at, CURRENT_TIMESTAMP) AS updated_at
        FROM keys
        ORDER BY id
        """
    ).fetchall()

    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("DROP TABLE IF EXISTS keys_v2")
    _create_keys_v2_table(conn, "keys_v2")

    for row in legacy_rows:
        legacy_name = row["key_type"].strip()
        key_type_id = type_ids.get(legacy_name.lower(), default_type_id)
        key_type_name = legacy_name or "Без типа"
        status = "issued_resident" if int(row["is_used"] or 0) else "free"

        conn.execute(
            """
            INSERT INTO keys_v2(
                id,
                key_type_id,
                number,
                hex_value,
                key_type,
                status,
                note,
                is_used,
                created_at,
                updated_at,
                created_by
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Система')
            """,
            (
                row["id"],
                key_type_id,
                str(row["number"]).strip(),
                str(row["hex_value"] or "").strip().upper(),
                key_type_name,
                status,
                row["note"],
                int(row["is_used"] or 0),
                row["created_at"],
                row["updated_at"],
            ),
        )

    conn.execute("DROP TABLE keys")
    conn.execute("ALTER TABLE keys_v2 RENAME TO keys")
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")
    _create_key_indexes(conn)


def _seed_key_assignments(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO key_assignments(
            key_id,
            assignment_type,
            employee_id,
            assigned_at,
            assigned_by,
            active,
            note
        )
        SELECT
            ek.key_id,
            'employee',
            ek.employee_id,
            ek.issued_at,
            'Система',
            1,
            ek.comment
        FROM employee_keys ek
        WHERE ek.status = 'active'
        """
    )

    conn.execute(
        """
        INSERT OR IGNORE INTO key_assignments(
            key_id,
            assignment_type,
            uk_group_id,
            assigned_at,
            assigned_by,
            active,
            note
        )
        SELECT
            gk.key_id,
            'uk',
            gk.group_id,
            CURRENT_TIMESTAMP,
            'Система',
            1,
            'Перенесено из связи с УК'
        FROM uk_group_keys gk
        WHERE NOT EXISTS (
            SELECT 1
            FROM key_assignments ka
            WHERE ka.key_id = gk.key_id AND ka.active = 1
        )
        """
    )

    conn.execute(
        """
        UPDATE keys
        SET status = 'issued_employee', is_used = 1
        WHERE id IN (
            SELECT key_id FROM key_assignments
            WHERE assignment_type = 'employee' AND active = 1
        )
        """
    )
    conn.execute(
        """
        UPDATE keys
        SET status = 'assigned_uk', is_used = 1
        WHERE id IN (
            SELECT key_id FROM key_assignments
            WHERE assignment_type = 'uk' AND active = 1
        )
        """
    )

def init_db():
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS key_types (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE COLLATE NOCASE NOT NULL,
                color TEXT NOT NULL DEFAULT '#2A9DF4',
                note TEXT DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key_type_id INTEGER NOT NULL,
                number TEXT NOT NULL,
                hex_value TEXT NOT NULL DEFAULT '',
                key_type TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'free',
                note TEXT DEFAULT '',
                is_used INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                created_by TEXT DEFAULT '',
                FOREIGN KEY(key_type_id)
                    REFERENCES key_types(id)
                    ON DELETE RESTRICT
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

            CREATE TABLE IF NOT EXISTS key_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key_id INTEGER NOT NULL,
                assignment_type TEXT NOT NULL,
                address TEXT DEFAULT '',
                apartment TEXT DEFAULT '',
                employee_id INTEGER DEFAULT NULL,
                uk_group_id INTEGER DEFAULT NULL,
                assigned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                assigned_by TEXT DEFAULT '',
                released_at TEXT DEFAULT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                note TEXT DEFAULT '',
                FOREIGN KEY(key_id) REFERENCES keys(id) ON DELETE RESTRICT,
                FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE SET NULL,
                FOREIGN KEY(uk_group_id) REFERENCES uk_groups(id) ON DELETE SET NULL
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
                panel_id INTEGER DEFAULT NULL,
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

            CREATE UNIQUE INDEX IF NOT EXISTS idx_key_assignments_one_active
            ON key_assignments(key_id)
            WHERE active = 1;

            CREATE INDEX IF NOT EXISTS idx_key_assignments_lookup
            ON key_assignments(assignment_type, active, assigned_at);
            """
        )

        _migrate_keys_inventory(conn)

        # Добавляет IP-адрес в существующую таблицу панелей.
        # Старые данные при этом не удаляются.
        _add_column_if_missing(
            conn,
            "panels",
            "ip",
            "ip TEXT DEFAULT ''",
        )
        panel_status_columns = {
            "api_status": "api_status TEXT DEFAULT 'unknown'",
            "last_checked_at": "last_checked_at TEXT DEFAULT ''",
            "last_online_at": "last_online_at TEXT DEFAULT ''",
            "response_time_ms": "response_time_ms INTEGER DEFAULT NULL",
            "device_model": "device_model TEXT DEFAULT ''",
            "firmware_version": "firmware_version TEXT DEFAULT ''",
            "temperature": "temperature REAL DEFAULT NULL",
            "supply_voltage": "supply_voltage REAL DEFAULT NULL",
            "uptime_seconds": "uptime_seconds INTEGER DEFAULT NULL",
            "sip_registered": "sip_registered INTEGER DEFAULT NULL",
            "reported_mac": "reported_mac TEXT DEFAULT ''",
            "last_error": "last_error TEXT DEFAULT ''",
        }
        for column_name, column_sql in panel_status_columns.items():
            _add_column_if_missing(conn, "panels", column_name, column_sql)

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_panels_api_status ON panels(enabled, api_status)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_panels_address_entrance ON panels(address, entrance)"
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
        _seed_key_assignments(conn)

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
            "panel_id": "panel_id INTEGER DEFAULT NULL",
            "username": "username TEXT DEFAULT ''",
            "user_full_name": "user_full_name TEXT DEFAULT ''",
            "user_role": "user_role TEXT DEFAULT ''",
            "ip_address": "ip_address TEXT DEFAULT ''",
            "key_id": "key_id INTEGER DEFAULT NULL",
            "key_type": "key_type TEXT DEFAULT ''",
            "employee_id": "employee_id INTEGER DEFAULT NULL",
            "uk_group_id": "uk_group_id INTEGER DEFAULT NULL",
            "comment": "comment TEXT DEFAULT ''",
        }

        for column_name, column_sql in operation_log_columns.items():
            _add_column_if_missing(
                conn,
                "operation_log",
                column_name,
                column_sql,
            )

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_operation_log_key_id ON operation_log(key_id)"
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_key_assignments_key_history
            ON key_assignments(key_id, active, assigned_at)
            """
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
