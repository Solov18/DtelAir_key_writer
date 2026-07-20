import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook

import app.db as database
from app.repositories import key_repository
from app.services.importer import import_keys_file
from app.services.writer import write_key_to_panels


class KeyInventoryTests(unittest.TestCase):
    def setUp(self):
        self._original_db_path = database.DB_PATH
        self._temporary_directory = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self._temporary_directory.name) / "test.db"
        database.init_db()

    def tearDown(self):
        database.DB_PATH = self._original_db_path
        self._temporary_directory.cleanup()

    def _create_key(self, key_type_id, number, hex_value):
        return key_repository.save_prepared_key(
            key_type_id,
            str(number),
            hex_value,
            "Тест",
        )

    def test_number_is_unique_only_inside_type(self):
        blue_id = key_repository.create_key_type("Синий", "#168EE8")
        orange_id = key_repository.create_key_type("Оранжевый", "#FF982A")

        blue = self._create_key(blue_id, 1, "AAAAAA01")
        orange = self._create_key(orange_id, 1, "BBBBBB01")

        self.assertNotEqual(blue["id"], orange["id"])
        with self.assertRaisesRegex(ValueError, "уже сохранён HEX"):
            self._create_key(blue_id, 1, "CCCCCC01")

    def test_key_types_expose_last_and_next_numeric_number(self):
        blue_id = key_repository.create_key_type("Синий", "#168EE8")
        empty_id = key_repository.create_key_type("Новый тип", "#22B889")
        padded_id = key_repository.create_key_type("С ведущими нулями", "#9B72E8")

        self._create_key(blue_id, 456788, "AABB0001")
        self._create_key(blue_id, 456789, "AABB0002")
        padded_batch = key_repository.prepare_key_range(
            padded_id,
            "0009",
            2,
            "Тест",
        )
        self._create_key(padded_id, "0009", "AABB0003")
        self._create_key(padded_id, "0010", "AABB0004")

        key_types = {
            item["id"]: item
            for item in key_repository.get_key_types(include_archived=False)
        }

        self.assertEqual(key_types[blue_id]["last_number"], "456789")
        self.assertEqual(key_types[blue_id]["next_number"], "456790")
        self.assertEqual(
            [item["number"] for item in padded_batch["rows"]],
            ["0009", "0010"],
        )
        self.assertEqual(key_types[padded_id]["last_number"], "0010")
        self.assertEqual(key_types[padded_id]["next_number"], "0011")
        self.assertEqual(key_types[empty_id]["last_number"], "")
        self.assertEqual(key_types[empty_id]["next_number"], "")

    def test_scanner_rejects_duplicate_hex(self):
        key_type_id = key_repository.create_key_type("Стикер", "#9B72E8")
        batch = key_repository.prepare_key_range(key_type_id, 10, 2, "Тест")
        first, second = batch["rows"]

        key_repository.save_prepared_key(
            key_type_id,
            first["number"],
            "363FFAD7",
            "Тест",
        )

        with self.assertRaisesRegex(ValueError, "уже принадлежит"):
            key_repository.save_prepared_key(
                key_type_id,
                second["number"],
                "36:3F:FA:D7",
                "Тест",
            )

    def test_prepare_skips_filled_numbers_and_protects_saved_hex(self):
        key_type_id = key_repository.create_key_type("Синий", "#168EE8")
        original = key_repository.prepare_key_range(key_type_id, 10, 2, "Тест")
        first, second = original["rows"]
        saved_first = key_repository.save_prepared_key(
            key_type_id,
            first["number"],
            "AABBCCDD",
            "Тест",
        )

        repeated = key_repository.prepare_key_range(key_type_id, 10, 2, "Тест")

        self.assertEqual(repeated["created"], 0)
        self.assertEqual(repeated["filled_existing"], 1)
        self.assertEqual(repeated["resumed"], 0)
        self.assertEqual([row["number"] for row in repeated["rows"]], [second["number"]])

        with self.assertRaisesRegex(ValueError, "уже сохранён HEX"):
            key_repository.save_prepared_key(
                key_type_id,
                first["number"],
                "11223344",
                "Тест",
            )

        corrected = key_repository.save_prepared_key(
            key_type_id,
            first["number"],
            "11223344",
            "Тест",
            allow_replace=True,
        )
        self.assertEqual(corrected["id"], saved_first["id"])
        self.assertEqual(corrected["hex_value"], "11223344")

    def test_preparation_does_not_create_keys_without_hex(self):
        key_type_id = key_repository.create_key_type("Синий", "#168EE8")

        batch = key_repository.prepare_key_range(key_type_id, 500001, 3, "Тест")

        with database.db() as conn:
            keys_before_scan = conn.execute("SELECT COUNT(*) FROM keys").fetchone()[0]
        self.assertEqual(keys_before_scan, 0)
        self.assertEqual(
            [row["number"] for row in batch["rows"]],
            ["500001", "500002", "500003"],
        )

        saved = self._create_key(key_type_id, 500001, "ABCD0001")
        with database.db() as conn:
            stored = conn.execute(
                "SELECT number, hex_value FROM keys WHERE id = ?",
                (saved["id"],),
            ).fetchone()
        self.assertEqual(tuple(stored), ("500001", "ABCD0001"))

    def test_legacy_blank_rows_are_hidden_and_reused(self):
        key_type_id = key_repository.create_key_type("Синий", "#168EE8")
        with database.db() as conn:
            blank_id = conn.execute(
                """
                INSERT INTO keys(key_type_id, number, hex_value, key_type, status)
                VALUES (?, '500099', '', 'Синий', 'free')
                """,
                (key_type_id,),
            ).lastrowid

        self.assertEqual(key_repository.get_keys_page()["total"], 0)
        self.assertEqual(key_repository.get_key_statistics()["total"], 0)
        key_type = next(
            item for item in key_repository.get_key_types() if item["id"] == key_type_id
        )
        self.assertEqual(key_type["keys_count"], 0)

        saved = self._create_key(key_type_id, 500099, "ABCD0099")

        self.assertEqual(saved["id"], blank_id)
        self.assertEqual(key_repository.get_keys_page()["total"], 1)
        self.assertEqual(key_repository.get_key_statistics()["total"], 1)

    def test_existing_key_cannot_be_cleared_or_blank_key_assigned(self):
        key_type_id = key_repository.create_key_type("Синий", "#168EE8")
        saved = self._create_key(key_type_id, 1523, "ABCD1523")

        with self.assertRaisesRegex(ValueError, "нельзя сохранить без HEX"):
            key_repository.update_key(
                saved["id"],
                key_type_id,
                "1523",
                "",
                "",
            )

        with database.db() as conn:
            blank_id = conn.execute(
                """
                INSERT INTO keys(key_type_id, number, hex_value, key_type, status)
                VALUES (?, '1524', '', 'Синий', 'free')
                """,
                (key_type_id,),
            ).lastrowid

        with self.assertRaisesRegex(ValueError, "без HEX нельзя назначить"):
            key_repository.set_key_assignment(blank_id, "resident", apartment="15")

    def test_assignment_updates_status_and_release_keeps_history(self):
        key_type_id = key_repository.create_key_type("Премиум", "#E8B630")
        key = self._create_key(key_type_id, 77, "AABBCCDD")

        key_repository.set_key_assignment(
            key["id"],
            "resident",
            address="Тепличная 63",
            apartment="15",
            assigned_by="Оператор",
        )
        assigned = key_repository.get_key(key["id"])

        self.assertEqual(assigned["status"], "issued_resident")
        self.assertEqual(assigned["assignment_text"], "Тепличная 63 / кв. 15")

        key_repository.release_key(key["id"], "Возвращён")
        released = key_repository.get_key(key["id"])
        assignments = key_repository.get_key_assignments(key["id"])

        self.assertEqual(released["status"], "free")
        self.assertIsNone(released["assignment_type"])
        self.assertEqual(len(assignments), 1)
        self.assertEqual(assignments[0]["active"], 0)

    def test_excel_import_rejects_rows_without_hex(self):
        workbook = Workbook()
        blue = workbook.active
        blue.title = "Синий"
        blue.append(["№", "HEX", "Комментарий"])
        blue.append([1, "363FFAD7", "Первый"])
        blue.append([2, "", "Заготовка"])
        orange = workbook.create_sheet("Оранжевый")
        orange.append(["Number", "Код"])
        orange.append([1, "3644D427"])
        content = io.BytesIO()
        workbook.save(content)

        first_report = import_keys_file("keys.xlsx", content.getvalue(), "Тест")

        self.assertEqual(first_report["created_types"], 2)
        self.assertEqual(first_report["added"], 2)
        self.assertEqual(first_report["errors"], 1)
        self.assertTrue(any("не указан HEX" in item for item in first_report["error_details"]))

        blue[3][1].value = "11223344"
        updated_content = io.BytesIO()
        workbook.save(updated_content)
        second_report = import_keys_file(
            "keys.xlsx",
            updated_content.getvalue(),
            "Тест",
        )

        self.assertEqual(second_report["added"], 1)
        self.assertGreaterEqual(second_report["duplicates"], 2)

    def test_problem_key_is_not_sent_to_crm(self):
        key_type_id = key_repository.create_key_type("Детский", "#5CC878")
        key = self._create_key(key_type_id, 15, "A1B2C3D4")
        key_repository.set_key_status(key["id"], "blocked", "Проверка")
        blocked_key = key_repository.get_key(key["id"])

        with patch("app.services.writer.crm_add_key") as crm_add_key:
            results = write_key_to_panels(
                "resident_manual",
                blocked_key,
                [{"id": 1, "name": "Вход", "mac": "08:55:CD:00:00:01"}],
                flat_num="15",
                address="Тепличная 63",
            )

        crm_add_key.assert_not_called()
        self.assertEqual(results[0]["status"], "KEY_UNAVAILABLE")
        self.assertFalse(results[0]["written"])

    def test_assignment_keeps_employee_and_uk_sections_in_sync(self):
        key_type_id = key_repository.create_key_type("Служебный", "#159ED9")
        key = self._create_key(key_type_id, 91, "A1B2C391")

        with database.db() as conn:
            employee_id = conn.execute(
                "INSERT INTO employees(full_name) VALUES ('Иванов Иван')"
            ).lastrowid
            group_id = conn.execute(
                "INSERT INTO uk_groups(name) VALUES ('УК Тест')"
            ).lastrowid
            conn.execute(
                """
                INSERT INTO employee_keys(employee_id, key_id, status)
                VALUES (?, ?, 'active')
                """,
                (employee_id, key["id"]),
            )

        key_repository.set_key_assignment(
            key["id"],
            "uk",
            uk_group_id=group_id,
            assigned_by="Тест",
        )

        with database.db() as conn:
            employee_status = conn.execute(
                "SELECT status FROM employee_keys WHERE key_id = ?",
                (key["id"],),
            ).fetchone()[0]
            uk_links = conn.execute(
                "SELECT COUNT(*) FROM uk_group_keys WHERE key_id = ?",
                (key["id"],),
            ).fetchone()[0]

        self.assertEqual(employee_status, "replaced")
        self.assertEqual(uk_links, 1)
        self.assertEqual(key_repository.get_key(key["id"])["status"], "assigned_uk")

        key_repository.release_key(key["id"], "Возвращён")

        with database.db() as conn:
            uk_links_after_release = conn.execute(
                "SELECT COUNT(*) FROM uk_group_keys WHERE key_id = ?",
                (key["id"],),
            ).fetchone()[0]

        self.assertEqual(uk_links_after_release, 0)
        self.assertEqual(key_repository.get_key(key["id"])["status"], "free")

    def test_panel_id_and_previous_address_remain_searchable_in_history(self):
        key_type_id = key_repository.create_key_type("Синий", "#168EE8")
        key = self._create_key(key_type_id, 1523, "363FFAD7")

        with patch(
            "app.services.writer.crm_add_key",
            return_value={
                "ok": True,
                "written": True,
                "status": "SUCCESS",
                "response": "Ключ успешно записан",
                "message": "Ключ успешно записан",
            },
        ):
            write_key_to_panels(
                "resident_manual",
                key,
                [
                    {
                        "id": 42,
                        "name": "Подъезд 1",
                        "mac": "08:55:CD:00:00:01",
                        "address": "Тепличная 63",
                    }
                ],
                flat_num="15",
                address="Тепличная 63",
                assignment_type="resident",
            )

        key_repository.release_key(key["id"], "Перенесён")

        with database.db() as conn:
            panel_id = conn.execute(
                "SELECT panel_id FROM operation_log WHERE key_id = ?",
                (key["id"],),
            ).fetchone()[0]

        self.assertEqual(panel_id, 42)
        self.assertEqual(key_repository.get_keys_page(query="Тепличная 63")["total"], 1)
        self.assertEqual(key_repository.get_keys_page(query="кв 15")["total"], 1)


if __name__ == "__main__":
    unittest.main()
