import asyncio
from unittest.mock import patch
from urllib.parse import urlencode

from starlette.requests import Request
from starlette.responses import PlainTextResponse

from tests.postgres_test_case import PostgreSQLTestCase

from app.db import db
from app.middleware import AuthMiddleware
from app.repositories.role_repository import (
    ADMIN_CRITICAL_PERMISSIONS,
    delete_role,
    get_role_by_code,
    get_roles,
    set_role_permissions,
)
from app.repositories.user_repository import create_user
from app.routers.settings import (
    crm_settings_check,
    crm_settings_page,
    roles_create,
    roles_page,
    security_log_page,
    settings_page,
    training_mode_toggle,
    work_mode_page,
)
from app.routers.users import users_active, users_delete, users_page
from app.services.auth import hash_password
from app.settings import settings


class SettingsAccessTests(PostgreSQLTestCase):
    def setUp(self):
        super().setUp()
        self.user_id = int(
            create_user(
                "Тестовый администратор",
                "settings-admin",
                hash_password("strong-password"),
                "admin",
            )
        )

    def _request(
        self,
        path: str,
        *,
        method: str = "GET",
        data: dict | None = None,
        csrf_token: str = "test-csrf-token",
    ) -> Request:
        body = urlencode(data or {}).encode("utf-8")
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
                "method": method,
                "path": path,
                "query_string": b"",
                "headers": headers,
                "client": ("127.0.0.1", 10000),
                "session": {
                    "user_id": self.user_id,
                    "csrf_token": csrf_token,
                    "user": {
                        "id": self.user_id,
                        "login": "settings-admin",
                        "full_name": "Тестовый администратор",
                        "role": "admin",
                    },
                },
            },
            receive=receive,
        )

    def test_csrf_and_all_settings_screens(self):
        middleware = AuthMiddleware(lambda scope, receive, send: None)

        async def accepted(_request):
            return PlainTextResponse("ok")

        denied_request = self._request(
            "/settings/training-mode",
            method="POST",
            data={"enabled": "1"},
        )
        denied = asyncio.run(middleware.dispatch(denied_request, accepted))
        self.assertEqual(denied.status_code, 403)

        allowed_request = self._request(
            "/settings/training-mode",
            method="POST",
            data={"enabled": "1", "csrf_token": "test-csrf-token"},
        )
        allowed = asyncio.run(middleware.dispatch(allowed_request, accepted))
        self.assertEqual(allowed.status_code, 200)

        pages = (
            settings_page(self._request("/settings")),
            work_mode_page(self._request("/settings/mode")),
            crm_settings_page(self._request("/settings/crm")),
            roles_page(self._request("/settings/roles")),
            security_log_page(self._request("/settings/security")),
            users_page(self._request("/users")),
        )
        for response in pages:
            self.assertEqual(response.status_code, 200)

        settings_html = pages[0].body.decode("utf-8")
        self.assertIn('href="/settings/mode"', settings_html)
        self.assertIn('id="appDialog"', settings_html)
        self.assertIn("/static/js/dialogs.js", settings_html)
        mode_html = pages[1].body.decode("utf-8")
        self.assertIn("Рабочий режим", mode_html)
        self.assertIn('data-confirm-action="Переключить режим"', mode_html)
        users_html = pages[-1].body.decode("utf-8")
        self.assertIn('data-user-filter="all"', users_html)
        self.assertIn('data-user-filter="admin"', users_html)
        self.assertIn("/static/js/users-filter.js", users_html)

        crm_html = pages[2].body.decode("utf-8")
        for secret in (settings.crm_password, settings.crm_cookie):
            if secret:
                self.assertNotIn(secret, crm_html)

    def test_training_mode_uses_current_session_and_writes_audit_log(self):
        request = self._request("/settings/training-mode", method="POST")
        response = training_mode_toggle(
            request,
            enabled=1,
            return_to="/settings/mode",
        )
        self.assertEqual(response.status_code, 303)
        self.assertTrue(request.session["training_mode"])
        self.assertIn("/settings/mode?notice=training_on", response.headers["location"])
        with db() as conn:
            row = conn.execute(
                """
                SELECT action, object_name, details
                FROM operation_log
                WHERE action = 'settings_training_mode'
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["action"], "settings_training_mode")

    def test_role_crud_critical_permissions_and_mocked_crm_check(self):
        response = roles_create(
            self._request("/settings/roles/create", method="POST"),
            name="Диспетчер",
            description="Тестовая роль",
            permissions=["view", "view_logs"],
        )
        self.assertEqual(response.status_code, 303)
        custom = next(role for role in get_roles() if role["name"] == "Диспетчер")
        self.assertEqual(custom["permissions"], {"view", "view_logs"})

        admin = get_role_by_code("admin")
        set_role_permissions(admin["id"], set())
        refreshed_admin = get_role_by_code("admin")
        self.assertTrue(
            ADMIN_CRITICAL_PERMISSIONS <= refreshed_admin["permissions"]
        )
        with self.assertRaises(ValueError):
            delete_role(admin["id"])

        request = self._request("/settings/crm/check", method="POST")
        with patch(
            "app.routers.settings.check_crm_connection",
            return_value={"ok": True, "message": "Мок: соединение доступно"},
        ) as check:
            result = crm_settings_check(request)
        self.assertEqual(result.status_code, 303)
        check.assert_called_once_with()
        with db() as conn:
            actions = {
                row["action"]
                for row in conn.execute(
                    """
                    SELECT action FROM operation_log
                    WHERE action IN ('role_create', 'settings_crm_check')
                    """
                )
            }
        self.assertEqual(actions, {"role_create", "settings_crm_check"})

    def test_last_administrator_cannot_disable_or_delete_self(self):
        request = self._request("/users/active", method="POST")
        disabled = users_active(
            request,
            user_id=self.user_id,
            active=0,
        )
        deleted = users_delete(
            self._request("/users/delete", method="POST"),
            user_id=self.user_id,
        )
        self.assertIn("self_disable", disabled.headers["location"])
        self.assertIn("self_delete", deleted.headers["location"])
