import asyncio
from urllib.parse import urlencode

from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from app.db import db
from app.middleware import AuthMiddleware
from app.repositories.role_repository import get_role_by_code, set_role_permissions
from app.repositories.user_repository import create_user
from app.routers.auth import login
from app.routers.search import search_page, search_suggestions
from app.services.auth import hash_password
from app.services.search import get_search_suggestions, universal_search
from tests.postgres_test_case import PostgreSQLTestCase


class LookupRoleTests(PostgreSQLTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.password = "lookup-strong-password"
        self.user_id = int(
            create_user(
                "Сотрудник справочной",
                "lookup-user",
                hash_password(self.password),
                "lookup",
            )
        )
        with db() as conn:
            key_type_id = int(
                conn.execute(
                    "INSERT INTO key_types(name, color) VALUES (?, ?)",
                    ("Синий", "#2A9DF4"),
                ).lastrowid
            )
            self.key_id = int(
                conn.execute(
                    """
                    INSERT INTO keys(key_type_id, number, hex_value, status)
                    VALUES (?, '000321', 'AABB0321', 'issued_resident')
                    """,
                    (key_type_id,),
                ).lastrowid
            )
            conn.execute(
                """
                INSERT INTO key_assignments(
                    key_id, assignment_type, address, apartment,
                    note, assigned_by, active
                ) VALUES (?, 'resident', ?, '17', 'Тестовый жилец', 'Тест', 1)
                """,
                (self.key_id, "ул. Справочная 10"),
            )
            conn.execute(
                """
                INSERT INTO panels(address, entrance, name, mac, enabled)
                VALUES (?, 'подъезд 1', 'Справочная панель', ?, 1)
                """,
                ("ул. Справочная 10", "08:13:CD:00:03:21"),
            )
            conn.execute(
                """
                INSERT INTO operation_log(
                    mode, printed_number, hex_value, flat_num, mac,
                    panel_name, status, address, apartment, action,
                    object_type, object_name, details, key_id
                ) VALUES (
                    'test', '000321', 'AABB0321', '17', '', '', 'SUCCESS',
                    ?, '17', 'Выдача ключа', 'key', 'Ключ №000321',
                    'Выдан жильцу', ?
                )
                """,
                ("ул. Справочная 10", self.key_id),
            )
            conn.execute(
                """
                INSERT INTO uk_groups(name, crm_login, crm_password)
                VALUES ('Справочная УК', 'hidden-lookup-login', 'hidden-lookup-password')
                """
            )

    def _session_user(self) -> dict:
        return {
            "id": self.user_id,
            "login": "lookup-user",
            "full_name": "Сотрудник справочной",
            "role": "lookup",
            "permissions": ["use_universal_search"],
            "active": 1,
        }

    def _request(
        self,
        path: str,
        *,
        method: str = "GET",
        data: dict | None = None,
        query_string: str = "",
    ) -> Request:
        payload = dict(data or {})
        if method not in {"GET", "HEAD", "OPTIONS"}:
            payload.setdefault("csrf_token", "lookup-csrf")
        body = urlencode(payload).encode("utf-8")
        sent = False

        async def receive():
            nonlocal sent
            if sent:
                return {"type": "http.request", "body": b"", "more_body": False}
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        headers = []
        if body:
            headers = [
                (b"content-type", b"application/x-www-form-urlencoded"),
                (b"content-length", str(len(body)).encode("ascii")),
            ]
        return Request(
            {
                "type": "http",
                "http_version": "1.1",
                "method": method,
                "scheme": "http",
                "path": path,
                "raw_path": path.encode("utf-8"),
                "query_string": query_string.encode("utf-8"),
                "headers": headers,
                "client": ("127.0.0.1", 10000),
                "server": ("test", 80),
                "session": {
                    "user_id": self.user_id,
                    "csrf_token": "lookup-csrf",
                    "user": self._session_user(),
                },
            },
            receive=receive,
        )

    @staticmethod
    async def _accepted(_request):
        return PlainTextResponse("ok")

    def _dispatch(self, path: str, *, method: str = "GET"):
        middleware = AuthMiddleware(lambda scope, receive, send: None)
        return asyncio.run(
            middleware.dispatch(
                self._request(path, method=method),
                self._accepted,
            )
        )

    def test_lookup_role_has_only_universal_search_permission(self):
        lookup = get_role_by_code("lookup")
        self.assertIsNotNone(lookup)
        self.assertTrue(lookup["is_system"])
        self.assertEqual(lookup["name"], "Справочная")
        self.assertEqual(lookup["permissions"], {"use_universal_search"})
        set_role_permissions(lookup["id"], {"view", "manage_keys"})
        self.assertEqual(
            get_role_by_code("lookup")["permissions"],
            {"use_universal_search"},
        )

        for role_code in ("admin", "operator", "viewer"):
            role = get_role_by_code(role_code)
            self.assertIn("use_universal_search", role["permissions"])
        self.assertIn("manage_settings", get_role_by_code("admin")["permissions"])
        self.assertIn("write_keys", get_role_by_code("operator")["permissions"])
        self.assertIn("view", get_role_by_code("viewer")["permissions"])

    def test_login_and_root_redirect_to_universal_search(self):
        anonymous_request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/login",
                "headers": [],
                "query_string": b"",
                "session": {},
            }
        )
        response = login(
            anonymous_request,
            login="lookup-user",
            password=self.password,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/search")

        root_response = self._dispatch("/")
        self.assertEqual(root_response.status_code, 303)
        self.assertEqual(root_response.headers["location"], "/search")

    def test_universal_search_and_suggestions_are_available(self):
        self.assertEqual(self._dispatch("/search").status_code, 200)
        self.assertEqual(
            self._dispatch("/api/search/suggestions").status_code,
            200,
        )
        self.assertEqual(self._dispatch("/search", method="POST").status_code, 200)
        self.assertEqual(self._dispatch("/logout", method="POST").status_code, 200)

        by_address = universal_search("Справочная 10 кв 17")
        self.assertEqual(
            [item["number"] for item in by_address["inventory_results"]],
            ["000321"],
        )
        by_number = universal_search("321")
        self.assertEqual(by_number["key"]["id"], self.key_id)
        by_hex = universal_search("AABB0321")
        self.assertEqual(by_hex["key"]["id"], self.key_id)
        self.assertEqual(
            universal_search(
                "hidden-lookup-login",
                include_uk_credentials=False,
            )["uk_results"],
            [],
        )
        self.assertEqual(
            get_search_suggestions(
                "hidden-lookup-login",
                scope="universal",
                include_uk_credentials=False,
            ),
            [],
        )

        with self.assertRaises(HTTPException) as denied:
            search_suggestions(
                self._request("/api/search/suggestions"),
                q="Справочная",
                scope="panels",
                limit=8,
            )
        self.assertEqual(denied.exception.status_code, 403)

    def test_forbidden_read_and_write_routes_are_blocked(self):
        for path in (
            "/keys",
            "/employees",
            "/panels",
            "/uk",
            "/log",
            "/settings",
            "/users",
            "/settings/roles",
            "/message",
            "/write/manual",
        ):
            response = self._dispatch(path)
            self.assertEqual(response.status_code, 303, path)
            self.assertTrue(response.headers["location"].startswith("/search"), path)

        for path in (
            "/keys/import",
            "/keys/1/edit",
            "/keys/export",
            "/employees/create",
            "/panels/import",
            "/uk/create",
            "/settings/roles/create",
            "/users/create",
            "/message/write",
            "/write/manual/write",
        ):
            response = self._dispatch(path, method="POST")
            self.assertEqual(response.status_code, 303, path)
            self.assertTrue(response.headers["location"].startswith("/search"), path)

        for path in ("/api/keys/search", "/api/panels/search"):
            self.assertEqual(self._dispatch(path).status_code, 403, path)

    def test_lookup_menu_and_results_are_read_only_and_secret_free(self):
        response = search_page(
            self._request("/search", query_string="q=Справочная"),
            q="Справочная",
        )
        html = response.body.decode("utf-8")
        nav = html.split('<nav class="sidebar-nav">', 1)[1].split("</nav>", 1)[0]
        self.assertIn("Универсальный поиск", nav)
        for label in (
            "Главная",
            "Из сообщения",
            "Обычная запись",
            "Сотрудники",
            "Управляющие компании",
            "Панели / Адреса",
            "База ключей",
            "Журнал операций",
            "Настройки",
        ):
            self.assertNotIn(label, nav)

        for forbidden_link in (
            'href="/keys',
            'href="/employees',
            'href="/panels',
            'href="/uk',
            'href="/log',
            'href="/settings',
            'href="/users',
        ):
            self.assertNotIn(forbidden_link, html)
        self.assertIn("Сотрудник справочной", html)
        self.assertIn('action="/logout"', html)
        self.assertIn('id="themeToggle"', html)
        self.assertNotIn("hidden-lookup-login", html)
        self.assertNotIn("hidden-lookup-password", html)
