from tests.postgres_test_case import PostgreSQLTestCase
from starlette.requests import Request
from unittest.mock import patch

from app.repositories import employee_repository, key_repository
from app.routers.employees import employee_create_and_issue_key, employee_issue_key
from app.services.search import get_search_suggestions
from app.services import KeyWriteResult


class EmployeeRepositoryTests(PostgreSQLTestCase):
    def setUp(self):
        super().setUp()

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

    def _create_key(self, number: int, hex_value: str) -> dict:
        return key_repository.save_prepared_key(
            self.key_type_id,
            str(number),
            hex_value,
            "Тест",
        )

    @staticmethod
    def _write_result(key_id: int, panel_ids: list[int], *, success: bool = True):
        return KeyWriteResult.from_writer(key_id, [
            {
                "panel": {"id": panel_id, "address": "Тестовая 1", "name": f"Панель {panel_id}"},
                "status": "SUCCESS" if success else "ERROR",
                "ok": success,
                "written": success,
                "response": "OK" if success else "Панель недоступна",
            }
            for panel_id in panel_ids
        ])

    def _request(self) -> Request:
        return Request({
            "type": "http",
            "method": "POST",
            "path": f"/employees/{self.employee_id}/keys/issue",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 10000),
            "session": {"user": {"id": 1, "full_name": "Тестовый оператор"}},
        })

    def test_missing_key_returns_actionable_message_instead_of_error(self):
        response = employee_issue_key(
            self._request(),
            self.employee_id,
            key_value="999999",
            key_type_id=0,
            new_key_comment="",
        )
        html = response.body.decode("utf-8")
        self.assertIn("Ключ не найден в базе CRM", html)
        self.assertIn("Добавить ключ в базу", html)

    def test_create_missing_key_and_issue_to_employee(self):
        response = employee_create_and_issue_key(
            self._request(),
            self.employee_id,
            key_type_id=self.key_type_id,
            number="99123",
            hex_value="AABBCC12",
            comment="Создан из выдачи сотруднику",
        )
        self.assertEqual(response.status_code, 303)
        key = key_repository.get_keys_page(query="99123")["items"][0]
        self.assertEqual(key["status"], "issued_employee")
        active = employee_repository.get_employee_active_keys(self.employee_id)
        self.assertEqual(active[0]["key_id"], key["id"])

    def test_employee_key_is_physically_written_to_selected_panels_before_assignment(self):
        key = self._create_key(99124, "AABBCC13")
        panels = [
            {"id": 41, "address": "Тестовая 1", "entrance": "вход 1", "mac": "08:13:CD:00:00:41"},
            {"id": 42, "address": "Тестовая 1", "entrance": "вход 2", "mac": "08:13:CD:00:00:42"},
        ]
        write_result = self._write_result(key["id"], [41, 42])
        request = self._request()
        with (
            patch("app.routers.employees.get_panels", return_value=panels) as get_panels,
            patch("app.routers.employees._employee_write_result", return_value=write_result) as write_key,
            patch("app.routers.employees.issue_key_to_employee") as issue_key,
            patch("app.routers.employees.log_event"),
        ):
            response = employee_issue_key(
                request,
                self.employee_id,
                key_value=key["number"],
                key_type_id=self.key_type_id,
                panel_ids=[41, 42, 41],
            )

        get_panels.assert_called_once_with(panel_ids=[41, 42])
        write_key.assert_called_once()
        actual_request, actual_employee, actual_key, actual_panels = write_key.call_args.args
        self.assertIs(actual_request, request)
        self.assertEqual(actual_employee["id"], self.employee_id)
        self.assertEqual(actual_key["id"], key["id"])
        self.assertEqual(actual_panels, panels)
        issue_key.assert_called_once()
        self.assertEqual(response.status_code, 200)

    def test_employee_key_can_be_explicitly_written_to_all_panels(self):
        key = self._create_key(99125, "AABBCC14")
        panels = [{"id": 51, "address": "Тестовая 2", "entrance": "вход", "mac": "08:13:CD:00:00:51"}]
        write_result = self._write_result(key["id"], [51])
        with (
            patch("app.routers.employees.get_panels", return_value=panels) as get_panels,
            patch("app.routers.employees._employee_write_result", return_value=write_result),
            patch("app.routers.employees.issue_key_to_employee") as issue_key,
            patch("app.routers.employees.log_event"),
        ):
            employee_issue_key(
                self._request(),
                self.employee_id,
                key_value=key["number"],
                key_type_id=self.key_type_id,
                panel_scope="all",
            )

        get_panels.assert_called_once_with()
        issue_key.assert_called_once()

    def test_employee_is_not_assigned_when_all_physical_writes_fail(self):
        key = self._create_key(99126, "AABBCC15")
        panels = [{"id": 61, "address": "Тестовая 3", "entrance": "вход", "mac": "08:13:CD:00:00:61"}]
        write_result = self._write_result(key["id"], [61], success=False)
        with (
            patch("app.routers.employees.get_panels", return_value=panels),
            patch("app.routers.employees._employee_write_result", return_value=write_result),
            patch("app.routers.employees.issue_key_to_employee") as issue_key,
            patch("app.routers.employees.log_event"),
        ):
            employee_issue_key(
                self._request(),
                self.employee_id,
                key_value=key["number"],
                key_type_id=self.key_type_id,
                panel_ids=[61],
            )

        issue_key.assert_not_called()

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

    def test_employee_history_exposes_readable_owner_and_audit_fields(self):
        key = self._create_key(55221, "AABBCCDD")
        assignment_id = employee_repository.issue_key_to_employee(
            self.employee_id,
            key["id"],
            new_key_comment="Служебный ключ",
        )
        employee_repository.close_employee_key(
            self.employee_id,
            assignment_id,
            "inactive",
            "Возвращён сотрудником",
        )

        history = employee_repository.get_employee_key_history(self.employee_id)

        self.assertEqual(history[0]["employee_name"], "Иванов Сергей Петрович")
        self.assertEqual(history[0]["close_reason"], "Возвращён сотрудником")
        self.assertIn("issued_by", history[0])
        self.assertIn("closed_by", history[0])


if __name__ == "__main__":
    unittest.main()
