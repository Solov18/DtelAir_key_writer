from urllib.parse import urlencode

from starlette.requests import Request

from app.db import db
from app.repositories.log_repository import count_operations, get_operations
from app.repositories.user_repository import create_user
from app.routers.log import log_page
from app.services.auth import hash_password
from tests.postgres_test_case import PostgreSQLTestCase


class OperationLogTests(PostgreSQLTestCase):
    def setUp(self):
        super().setUp()
        self.admin_id = int(
            create_user("Иван Администратор", "ivan.admin", hash_password("password"), "admin")
        )
        self.operator_id = int(
            create_user("Ольга Оператор", "olga.operator", hash_password("password"), "operator")
        )
        self._insert(
            created_at="2026-07-01 08:00:00",
            username="ivan.admin",
            user_full_name="Иван Администратор",
            action="user_create",
            object_type="Пользователь",
            object_name="Новый пользователь",
            status="success",
            details="Создан пользователь",
        )
        self._insert(
            created_at="2026-07-10 09:00:00",
            username="olga.operator",
            user_full_name="Ольга Оператор",
            action="employee_update",
            object_type="Сотрудник",
            object_name="Петров Пётр",
            employee_id=17,
            status="warning",
            details="Изменена должность",
        )
        self._insert(
            created_at="2026-07-20 10:00:00",
            username="ivan.admin",
            user_full_name="Иван Администратор",
            action="panel_reboot",
            object_type="Панель",
            object_name="Подъезд 1",
            panel_id=5,
            status="CONNECTION_ERROR",
            details="password=very secret, Cookie: session-cookie; token=abc-123",
        )
        self._insert(
            created_at="2026-07-21 11:00:00",
            username="ivan.admin",
            user_full_name="Иван Администратор",
            action="key_update",
            object_type="Ключ",
            object_name="500100",
            key_id=11,
            status="success",
            details="Изменён HEX ключа",
        )

    def _insert(self, **values):
        defaults = {
            "mode": values.get("action", "test"),
            "hex_value": "-",
            "mac": "",
            "status": "success",
            "created_at": "2026-07-01 00:00:00",
            "username": "",
            "user_full_name": "",
            "action": "test",
            "object_type": "",
            "object_name": "",
            "details": "",
            "key_id": None,
            "employee_id": None,
            "uk_group_id": None,
            "panel_id": None,
        }
        defaults.update(values)
        with db() as conn:
            conn.execute(
                """
                INSERT INTO operation_log(
                    mode, hex_value, mac, status, created_at,
                    username, user_full_name, action, object_type,
                    object_name, details, key_id, employee_id,
                    uk_group_id, panel_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                tuple(defaults[key] for key in (
                    "mode", "hex_value", "mac", "status", "created_at",
                    "username", "user_full_name", "action", "object_type",
                    "object_name", "details", "key_id", "employee_id",
                    "uk_group_id", "panel_id",
                )),
            )

    def _request(self, params: dict | None = None) -> Request:
        query_string = urlencode(params or {}).encode("utf-8")
        return Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/log",
                "query_string": query_string,
                "headers": [],
                "client": ("127.0.0.1", 10000),
                "session": {
                    "user_id": self.admin_id,
                    "user": {
                        "id": self.admin_id,
                        "login": "ivan.admin",
                        "full_name": "Иван Администратор",
                        "role": "admin",
                    },
                },
            }
        )

    def test_filter_by_period(self):
        rows = get_operations(date_from="2026-07-10", date_to="2026-07-20")
        self.assertEqual([row["action_key"] for row in rows], ["panel_reboot", "employee_update"])

    def test_filter_by_user(self):
        rows = get_operations(user_id=self.operator_id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["username"], "olga.operator")

    def test_filter_by_action(self):
        rows = get_operations(action="key_update")
        self.assertEqual([row["object_name"] for row in rows], ["500100"])

    def test_filter_by_object_type(self):
        self.assertEqual(count_operations(object_type="panel"), 1)
        self.assertEqual(count_operations(object_type="employee"), 1)

    def test_filter_by_status(self):
        self.assertEqual(count_operations(status="success"), 2)
        self.assertEqual(count_operations(status="warning"), 1)
        self.assertEqual(count_operations(status="error"), 1)

    def test_combined_filters_and_smart_search(self):
        rows = get_operations(
            date_from="2026-07-01",
            date_to="2026-07-15",
            user_id=self.operator_id,
            object_type="employee",
            status="warning",
            search="петров-петр",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["action_key"], "employee_update")

    def test_search_uses_localized_action_name(self):
        rows = get_operations(search="перезагрузка панели")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["action_key"], "panel_reboot")

    def test_pagination_and_sort_order(self):
        first_page = get_operations(limit=2, offset=0, sort_order="desc")
        second_page = get_operations(limit=2, offset=2, sort_order="desc")
        oldest = get_operations(limit=1, sort_order="asc")
        self.assertEqual([row["action_key"] for row in first_page], ["key_update", "panel_reboot"])
        self.assertEqual([row["action_key"] for row in second_page], ["employee_update", "user_create"])
        self.assertEqual(oldest[0]["action_key"], "user_create")

    def test_secrets_are_redacted_in_every_output_field(self):
        row = get_operations(action="panel_reboot")[0]
        rendered = " ".join(str(value) for value in row.values())
        self.assertNotIn("very secret", rendered)
        self.assertNotIn("session-cookie", rendered)
        self.assertNotIn("abc-123", rendered)
        self.assertIn("[СКРЫТО]", rendered)

    def test_route_persists_filters_and_reset_is_clean(self):
        filtered = log_page(
            self._request(
                {
                    "date_from": "2026-07-10",
                    "user_id": str(self.operator_id),
                    "status": "warning",
                    "search": "Петров",
                    "page": "4",
                }
            )
        )
        self.assertEqual(filtered.context["filters"]["period"], "custom")
        self.assertEqual(filtered.context["filters"]["user_id"], self.operator_id)
        self.assertEqual(filtered.context["filters"]["search"], "Петров")
        self.assertEqual(filtered.context["page"], 1)

        reset = log_page(self._request())
        self.assertEqual(reset.context["filters"]["period"], "all")
        self.assertIsNone(reset.context["filters"]["user_id"])
        self.assertEqual(reset.context["filters"]["search"], "")
