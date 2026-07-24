import sqlite3
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, select

from app.models import employees, metadata, users
from scripts.migrate_sqlite_to_postgres import (
    file_sha256,
    migrate_rows,
    open_legacy_database,
)


class DatabaseMigrationTests(unittest.TestCase):
    def test_employees_and_users_keep_ids_and_source_is_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_path = root / "legacy.db"
            target_path = root / "target.db"
            source = sqlite3.connect(source_path)
            try:
                source.executescript(
                    """
                    CREATE TABLE employees (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        full_name TEXT NOT NULL,
                        note TEXT DEFAULT '',
                        enabled INTEGER DEFAULT 1,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT DEFAULT '',
                        dismissed_at TEXT DEFAULT NULL,
                        position TEXT DEFAULT '',
                        department TEXT DEFAULT '',
                        phone TEXT DEFAULT '',
                        email TEXT DEFAULT '',
                        created_by TEXT DEFAULT ''
                    );
                    CREATE TABLE users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        full_name TEXT NOT NULL,
                        login TEXT UNIQUE NOT NULL,
                        password_hash TEXT NOT NULL,
                        role TEXT NOT NULL DEFAULT 'operator',
                        active INTEGER DEFAULT 1,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                        last_login TEXT DEFAULT ''
                    );
                    """
                )
                source.execute(
                    """
                    INSERT INTO employees(
                        id, full_name, note, enabled, created_at, updated_at,
                        dismissed_at, position, department, phone, email,
                        created_by
                    )
                    VALUES (77, 'Иванов Иван', '', 1, '2026-07-24 10:00:00',
                            '', NULL, 'Инженер', 'Технический', '', '', 'Тест')
                    """
                )
                source.execute(
                    """
                    INSERT INTO users(
                        id, full_name, login, password_hash, role, active,
                        created_at, last_login
                    )
                    VALUES (12, 'Администратор', 'admin', 'hash', 'admin', 1,
                            '2026-07-24 10:00:00', '')
                    """
                )
                source.commit()
            finally:
                source.close()

            before_hash = file_sha256(source_path)
            target_engine = create_engine(f"sqlite+pysqlite:///{target_path}")
            metadata.create_all(target_engine)
            legacy = open_legacy_database(source_path)
            try:
                result = migrate_rows(legacy, target_engine)
            finally:
                legacy.close()

            self.assertEqual(result["employees"], (1, 1))
            self.assertEqual(result["users"], (1, 1))
            with target_engine.connect() as connection:
                self.assertEqual(
                    connection.scalar(select(employees.c.id)),
                    77,
                )
                self.assertEqual(
                    connection.scalar(select(users.c.id)),
                    12,
                )
            target_engine.dispose()
            self.assertEqual(before_hash, file_sha256(source_path))


if __name__ == "__main__":
    unittest.main()
