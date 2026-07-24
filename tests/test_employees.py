import tempfile
import unittest
from pathlib import Path

import app.db as database
from app.repositories import employee_repository, key_repository
from app.services.search import get_search_suggestions


class EmployeeRepositoryTests(unittest.TestCase):
    def setUp(self):
        self._original_db_path = database.DB_PATH
        self._temporary_directory = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self._temporary_directory.name) / "test.db"
        database.init_db()

        self.key_type_id = key_repository.create_key_type(
            "Синий",
            "#168EE8",
        )
        self.employee_id = employee_repository.create_employee(
            "Иванов Сергей Петрович",
            position="Инженер",
            department="Технический отдел",
            phone="+7 (999) 123-45-67",
            email="ivanov@dtel.ru",
        )

    def tearDown(self):
        database.DB_PATH = self._original_db_path
        self._temporary_directory.cleanup()

    def _create_key(self, number: int, hex_value: str) -> dict:
        return key_repository.save_prepared_key(
            self.key_type_id,
            str(number),
            hex_value,
            "Тест",
        )

    def test_employee_can_have_several_active_keys(self):
        first = self._create_key(1523, "363FFAD7")
        second = self._create_key(1524, "363FFAD8")

        employee_repository.issue_key_to_employee(
            self.employee_id,
            first["id"],
        )
        employee_repository.issue_key_to_employee(
            self.employee_id,
            second["id"],
        )

        active_keys = employee_repository.get_employee_active_keys(
            self.employee_id
        )

        self.assertEqual(
            {item["number"] for item in active_keys},
            {"1523", "1524"},
        )
        self.assertEqual(
            key_repository.get_key(first["id"])["status"],
            "issued_employee",
        )
        self.assertEqual(
            key_repository.get_key(second["id"])["status"],
            "issued_employee",
        )

    def test_one_key_cannot_be_active_for_two_employees(self):
        key = self._create_key(1523, "363FFAD7")
        other_employee_id = employee_repository.create_employee(
            "Петров Алексей Викторович"
        )

        employee_repository.issue_key_to_employee(
            self.employee_id,
            key["id"],
        )

        with self.assertRaisesRegex(ValueError, "уже используется"):
            employee_repository.issue_key_to_employee(
                other_employee_id,
                key["id"],
            )

    def test_closing_one_key_keeps_other_key_active(self):
        first = self._create_key(1523, "363FFAD7")
        second = self._create_key(1524, "363FFAD8")
        first_assignment = employee_repository.issue_key_to_employee(
            self.employee_id,
            first["id"],
        )
        employee_repository.issue_key_to_employee(
            self.employee_id,
            second["id"],
        )

        employee_repository.close_employee_key(
            self.employee_id,
            first_assignment,
            "inactive",
            "Возвращён сотрудником",
        )

        active_keys = employee_repository.get_employee_active_keys(
            self.employee_id
        )
        self.assertEqual(
            [item["number"] for item in active_keys],
            ["1524"],
        )
        self.assertEqual(key_repository.get_key(first["id"])["status"], "free")
        self.assertEqual(
            key_repository.get_key(second["id"])["status"],
            "issued_employee",
        )

    def test_dismissal_releases_all_active_keys(self):
        first = self._create_key(1523, "363FFAD7")
        second = self._create_key(1524, "363FFAD8")
        employee_repository.issue_key_to_employee(
            self.employee_id,
            first["id"],
        )
        employee_repository.issue_key_to_employee(
            self.employee_id,
            second["id"],
        )

        employee_repository.dismiss_employee(
            self.employee_id,
            "Уволен",
        )

        self.assertEqual(
            employee_repository.get_employee_active_keys(self.employee_id),
            [],
        )
        self.assertEqual(key_repository.get_key(first["id"])["status"], "free")
        self.assertEqual(key_repository.get_key(second["id"])["status"], "free")

    def test_employee_search_ignores_case_and_punctuation(self):
        key = self._create_key(1523, "36:3F:FA:D7")
        employee_repository.issue_key_to_employee(
            self.employee_id,
            key["id"],
        )

        by_name = employee_repository.get_employee_page(
            query="ИВАНОВ.СЕРГЕЙ",
        )
        by_phone = employee_repository.get_employee_page(
            query="79991234567",
        )
        by_hex = employee_repository.get_employee_page(
            query="363f.fa-d7",
        )

        self.assertEqual(by_name["total"], 1)
        self.assertEqual(by_phone["total"], 1)
        self.assertEqual(by_hex["total"], 1)

    def test_suggestions_return_similar_employee_before_submit(self):
        suggestions = get_search_suggestions(
            "иванов. сер",
            scope="employees",
        )

        self.assertTrue(suggestions)
        self.assertEqual(
            suggestions[0]["value"],
            "Иванов Сергей Петрович",
        )

    def test_key_registry_search_ignores_hex_punctuation(self):
        key = self._create_key(1523, "363FFAD7")

        page = key_repository.get_keys_page(query="36:3f.fa-d7")

        self.assertEqual(page["total"], 1)
        self.assertEqual(page["items"][0]["id"], key["id"])


if __name__ == "__main__":
    unittest.main()
