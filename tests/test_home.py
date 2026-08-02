from datetime import datetime
from unittest.mock import patch

from sqlalchemy import event
from starlette.requests import Request

from tests.postgres_test_case import PostgreSQLTestCase

from app import db as database
from app.db import db
from app.routers.home import index
from app.services.dashboard import build_calendar, format_monitor_sync


ALL_PERMISSIONS = {
    "view",
    "write_keys",
    "manage_keys",
    "manage_panels",
    "manage_uk",
    "manage_employees",
    "view_logs",
    "manage_users",
    "manage_settings",
}


class HomeDashboardTests(PostgreSQLTestCase):
    def _request(self, permissions=None) -> Request:
        return Request(
            {
                "type": "http",
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": "/",
                "raw_path": b"/",
                "query_string": b"",
                "headers": [],
                "client": ("127.0.0.1", 1234),
                "server": ("test", 80),
                "session": {
                    "user": {
                        "id": 1,
                        "login": "admin",
                        "full_name": "Администратор",
                        "role": "admin",
                        "permissions": sorted(
                            ALL_PERMISSIONS if permissions is None else permissions
                        ),
                        "active": 1,
                    }
                },
            }
        )

    def _seed_dashboard(self) -> None:
        with db() as conn:
            conn.executemany(
                "INSERT INTO employees(full_name, enabled) VALUES (?, ?)",
                (("Активный", 1), ("Уволенный", 0)),
            )
            conn.executemany(
                """
                INSERT INTO uk_groups(name, archived_at)
                VALUES (?, ?)
                """,
                (
                    ("Рабочая УК", None),
                    ("Архивная УК", datetime(2026, 7, 1, 10, 0)),
                ),
            )
            conn.executemany(
                """
                INSERT INTO panels(
                    address, entrance, name, mac, enabled, api_status,
                    last_checked_at, supply_voltage, sip_registered
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        "Адрес 1", "1", "Онлайн", "00:00:00:00:00:01",
                        1, "online", datetime(2026, 7, 31, 8, 0), 13.0, 1,
                    ),
                    (
                        "Адрес 2", "2", "Оффлайн", "00:00:00:00:00:02",
                        1, "offline", datetime(2026, 7, 31, 8, 1), 12.7, 0,
                    ),
                    (
                        "Адрес 3", "3", "Отключена", "00:00:00:00:00:03",
                        0, "offline", datetime(2026, 7, 31, 8, 2), 12.0, 0,
                    ),
                    (
                        "Адрес 4", "4", "Нет данных", "00:00:00:00:00:04",
                        1, "unknown", None, None, None,
                    ),
                ),
            )
            key_type_id = conn.execute(
                "INSERT INTO key_types(name) VALUES (?)",
                ("Синий",),
            ).lastrowid
            conn.executemany(
                """
                INSERT INTO keys(key_type_id, number, hex_value)
                VALUES (?, ?, ?)
                """,
                (
                    (key_type_id, "1", "AABBCC01"),
                    (key_type_id, "2", ""),
                ),
            )
            conn.execute(
                """
                INSERT INTO panel_monitor_state(
                    id, status, completed, online, failed, finished_at
                )
                VALUES (1, 'completed', 3, 1, 1, ?)
                """,
                (datetime(2026, 7, 31, 9, 32),),
            )
            for index in range(6):
                conn.execute(
                    """
                    INSERT INTO operation_log(
                        mode, action, object_type, object_name, hex_value,
                        mac, status, created_at, username, user_full_name
                    )
                    VALUES (?, ?, ?, ?, '-', '', ?, ?, ?, ?)
                    """,
                    (
                        "panel_check",
                        "panel_check",
                        "Панель",
                        f"Панель {index}",
                        "warning" if index == 4 else "success",
                        f"2026-07-31 09:3{index}:00",
                        "admin",
                        "Администратор",
                    ),
                )

    def test_home_uses_saved_values_real_counters_and_five_recent_logs(self):
        self._seed_dashboard()

        with patch("requests.sessions.Session.request") as external_request:
            response = index(self._request())

        self.assertEqual(response.status_code, 200)
        external_request.assert_not_called()
        html = response.body.decode("utf-8")

        self.assertIn("Управление доступом", html)
        self.assertIn("Панели в сети", html)
        self.assertIn(">1</b>", html)
        self.assertIn("Панели с низким напряжением", html)
        self.assertIn("Проблемы с SIP-авторизацией", html)
        self.assertIn('href="/panels?status=sip_error"', html)
        self.assertIn('href="/panels?status=online"', html)
        self.assertIn('href="/panels?status=voltage_alert"', html)
        self.assertIn('href="/panels?status=offline"', html)
        self.assertIn("Панели не в сети", html)
        self.assertIn("С предупреждениями", html)
        self.assertIn("Панель 5", html)
        self.assertNotIn("Панель 0", html)
        self.assertEqual(html.count('class="operations-row"'), 5)
        self.assertLess(html.index("Панель 5"), html.index("Панель 4"))

        self.assertIn("<b>2</b><small>Сотрудники</small>", html)
        self.assertIn("<b>1</b><small>Управляющие", html)
        self.assertIn("<b>4</b><small>Панели / Адреса</small>", html)
        self.assertIn("<b>1</b><small>Ключи в базе</small>", html)
        self.assertIn("<b>6</b><small>Операции</small>", html)

    def test_sip_without_saved_values_is_not_shown_as_zero(self):
        with db() as conn:
            conn.execute(
                """
                INSERT INTO panels(
                    address, name, mac, enabled, api_status, last_checked_at
                )
                VALUES ('Адрес', 'Панель', '00:00:00:00:10:01', 1, 'online', CURRENT_TIMESTAMP)
                """
            )

        html = index(self._request()).body.decode("utf-8")
        sip_section = html.split("Проблемы с SIP-авторизацией", 1)[1].split(
            "</article>", 1
        )[0]
        self.assertIn("Нет данных", sip_section)
        self.assertNotIn(">0</b>", sip_section)

    def test_permissions_hide_unavailable_quick_actions_without_holes(self):
        html = index(self._request({"view"})).body.decode("utf-8")
        quick_grid = html.split('class="dashboard-quick-grid"', 1)[1].split(
            "</article>", 1
        )[0]
        self.assertNotIn("Добавить сотрудника", quick_grid)
        self.assertNotIn("Добавить УК", quick_grid)
        self.assertNotIn("База ключей", quick_grid)
        self.assertNotIn("Мониторинг панелей", quick_grid)
        self.assertNotIn("Журнал действий", quick_grid)
        self.assertNotIn(">Настройки</b>", quick_grid)
        self.assertIn("Поиск по реестру", quick_grid)
        self.assertIn("Календарь", quick_grid)

    def test_home_has_no_n_plus_one_queries(self):
        self._seed_dashboard()
        engine = database.get_engine()
        statements = []

        def record_query(_conn, _cursor, statement, _parameters, _context, _many):
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", record_query)
        try:
            response = index(self._request())
        finally:
            event.remove(engine, "before_cursor_execute", record_query)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(statements), 2)

    def test_home_html_does_not_include_environment_secrets(self):
        secret_values = (
            "crm-login-secret",
            "crm-password-secret",
            "crm-cookie-secret",
            "panel-login-secret",
            "panel-password-secret",
            "database-url-secret",
            "session-secret",
        )
        html = index(self._request()).body.decode("utf-8")
        for secret in secret_values:
            self.assertNotIn(secret, html)

    def test_calendar_and_localized_sync_labels(self):
        now = datetime.fromisoformat("2026-07-31T12:00:00+03:00")
        calendar = build_calendar(now=now)
        self.assertEqual(calendar["month_name"], "Июль")
        self.assertEqual(calendar["year"], 2026)
        self.assertEqual(
            sum(
                1
                for week in calendar["weeks"]
                for item in week
                if item["today"]
            ),
            1,
        )
        self.assertEqual(
            format_monitor_sync(
                datetime.fromisoformat("2026-07-31T09:32:00+03:00"),
                now=now,
            ),
            "Сегодня, 09:32",
        )
        self.assertEqual(
            format_monitor_sync(
                datetime.fromisoformat("2026-07-30T23:15:00+03:00"),
                now=now,
            ),
            "Вчера, 23:15",
        )
