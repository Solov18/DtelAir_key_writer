from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from openpyxl import Workbook

import app.db as database
from app.services.legacy_issued_keys import (
    LEGACY_ASSIGNMENT_NOTE,
    LEGACY_FREE_NOTE,
    LegacyIssuedKeyRow,
    import_legacy_free_keys,
    import_legacy_issued_keys,
    read_legacy_issued_workbook,
)
from tests.postgres_test_case import PostgreSQLTestCase


class LegacyIssuedKeysTests(PostgreSQLTestCase):
    def _seed_catalog(self):
        with database.db() as conn:
            blue = conn.execute(
                "INSERT INTO key_types(name, color) VALUES ('Синий', '#168EE8')"
            ).lastrowid
            premium = conn.execute(
                "INSERT INTO key_types(name, color) VALUES ('Премиальные', '#9B72E8')"
            ).lastrowid
            conn.execute(
                """
                INSERT INTO panels(address, entrance, name, mac, enabled)
                VALUES
                    ('ул. Тепличная 83', 'подъезд 1', 'Тепличная 83', '08:13:CD:00:00:01', 1),
                    ('ул. Искры 66/8', 'подъезд 1', 'Искры 66/8', '08:13:CD:00:00:02', 1)
                """
            )
        return int(blue), int(premium)

    def test_apply_is_idempotent_and_never_calls_panel_writer(self):
        blue, _ = self._seed_catalog()
        with database.db() as conn:
            existing_id = conn.execute(
                """
                INSERT INTO keys(
                    key_type_id, number, hex_value, key_type, status, is_used
                )
                VALUES (?, '1', 'F043D6B0', 'Синий', 'free', 0)
                """,
                (blue,),
            ).lastrowid

        rows = [
            LegacyIssuedKeyRow("строка 2", "синий", "1", "F043D6B0", "Тепличная 83 кв. 47"),
            LegacyIssuedKeyRow("строка 3", "синий", "2", "F05EEF70", "Искры 66/8 кв 134"),
        ]
        with patch("app.services.writer.write_key_to_panels") as panel_writer:
            first = import_legacy_issued_keys(
                rows,
                actor="Тест импорта",
                dry_run=False,
                source_name="добавить.xlt",
                source_hash="test-hash",
            )
            second = import_legacy_issued_keys(
                rows,
                actor="Тест импорта",
                dry_run=False,
                source_name="добавить.xlt",
                source_hash="test-hash",
            )
        panel_writer.assert_not_called()

        self.assertEqual(first["found_keys"], 1)
        self.assertEqual(first["created_only_crm"], 1)
        self.assertEqual(first["linked_to_addresses"], 2)
        self.assertEqual(first["assignments_created_or_changed"], 2)
        self.assertEqual(first["panel_requests"], 0)
        self.assertEqual(second["found_keys"], 2)
        self.assertEqual(second["created_only_crm"], 0)
        self.assertEqual(second["already_linked"], 2)

        with database.db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM keys").fetchone()[0], 2)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM key_assignments WHERE active = 1").fetchone()[0],
                2,
            )
            stored = conn.execute(
                "SELECT status, is_used FROM keys WHERE id = ?",
                (existing_id,),
            ).fetchone()
            self.assertEqual(stored["status"], "issued_resident")
            self.assertEqual(stored["is_used"], 1)
            notes = [
                row["note"]
                for row in conn.execute(
                    "SELECT note FROM key_assignments ORDER BY key_id"
                )
            ]
            self.assertEqual(notes, [LEGACY_ASSIGNMENT_NOTE, LEGACY_ASSIGNMENT_NOTE])

    def test_dry_run_reports_bad_rows_without_writes(self):
        self._seed_catalog()
        rows = [
            LegacyIssuedKeyRow("строка 2", "синий", "1", "F043D6B0", "Неизвестная 999 кв. 1"),
            LegacyIssuedKeyRow("строка 3", "синий", "2", "", "Тепличная 83 кв. 2"),
            LegacyIssuedKeyRow("строка 4", "синий", "3", "F043D6C0", ""),
            LegacyIssuedKeyRow(
                "строка 5",
                "синий",
                "4",
                "F043D6D0",
                "Тепличная 83 кв. 4 / Искры 66/8 кв. 5",
            ),
        ]
        report = import_legacy_issued_keys(rows, actor="Тест", dry_run=True)
        self.assertTrue(report["dry_run"])
        self.assertEqual(report["addresses_not_found"], 2)
        self.assertEqual(report["errors"], 1)
        self.assertEqual(report["skipped_without_address"], 1)
        with database.db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM keys").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM key_assignments").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM operation_log").fetchone()[0], 0)

    def test_workbook_reader_understands_type_sections(self):
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "Лист1"
        worksheet.append(["синий", None, None])
        worksheet.append([1, "F043D6B0", "Тепличная 83 кв. 47"])
        worksheet.append([2, "F05EEF70", None])
        worksheet.append(["премиальный", None, None])
        worksheet.append([1, "AABBCC01", "Искры 66/8 кв. 134"])
        with TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.xlsx"
            workbook.save(path)
            rows = read_legacy_issued_workbook(path)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0].type_name, "синий")
        self.assertEqual(rows[2].type_name, "премиальный")
        self.assertEqual(rows[2].number, "1")

    def test_free_import_creates_only_missing_keys_and_preserves_issued(self):
        blue, _ = self._seed_catalog()
        with database.db() as conn:
            issued_id = conn.execute(
                """
                INSERT INTO keys(
                    key_type_id, number, hex_value, key_type, status, is_used, note
                )
                VALUES (?, '1', 'F043D6B0', 'Синий', 'issued_resident', 1, 'Выдан ранее')
                """,
                (blue,),
            ).lastrowid
            conn.execute(
                """
                INSERT INTO key_assignments(
                    key_id, assignment_type, address, apartment, active, note
                )
                VALUES (?, 'resident', 'ул. Тепличная 83', '47', 1, 'Старое назначение')
                """,
                (issued_id,),
            )

        rows = [
            LegacyIssuedKeyRow("строка 2", "синий", "1", "F043D6B0", ""),
            LegacyIssuedKeyRow("строка 3", "синий", "2", "F05EEF70", ""),
            LegacyIssuedKeyRow("строка 4", "синий", "3", "", ""),
            LegacyIssuedKeyRow("строка 5", "синий", "4", "F043D6D0", "Тепличная 83 кв. 4"),
        ]
        with patch("app.services.writer.write_key_to_panels") as panel_writer:
            first = import_legacy_free_keys(
                rows,
                actor="Тест импорта",
                dry_run=False,
                source_name="добавить.xlt",
                source_hash="test-hash",
            )
            second = import_legacy_free_keys(
                rows,
                actor="Тест импорта",
                dry_run=False,
                source_name="добавить.xlt",
                source_hash="test-hash",
            )
        panel_writer.assert_not_called()

        self.assertEqual(first["free_rows_in_file"], 3)
        self.assertEqual(first["created_in_crm"], 1)
        self.assertEqual(first["already_existed"], 1)
        self.assertEqual(first["unprocessed"], 1)
        self.assertEqual(first["panel_requests"], 0)
        self.assertEqual(second["created_in_crm"], 0)
        self.assertEqual(second["already_existed"], 2)

        with database.db() as conn:
            issued = conn.execute(
                "SELECT status, is_used, note FROM keys WHERE id = ?",
                (issued_id,),
            ).fetchone()
            self.assertEqual(dict(issued.items()), {
                "status": "issued_resident",
                "is_used": 1,
                "note": "Выдан ранее",
            })
            assignment = conn.execute(
                "SELECT address, apartment, note FROM key_assignments WHERE key_id = ? AND active = 1",
                (issued_id,),
            ).fetchone()
            self.assertEqual(dict(assignment.items()), {
                "address": "ул. Тепличная 83",
                "apartment": "47",
                "note": "Старое назначение",
            })
            created = conn.execute(
                "SELECT status, is_used, note FROM keys WHERE number = '2'",
            ).fetchone()
            self.assertEqual(dict(created.items()), {
                "status": "free",
                "is_used": 0,
                "note": LEGACY_FREE_NOTE,
            })
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM key_assignments").fetchone()[0],
                1,
            )
