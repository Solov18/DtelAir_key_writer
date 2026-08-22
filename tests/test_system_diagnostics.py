import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests

from tests.postgres_test_case import PostgreSQLTestCase

from app.repositories.system_settings_repository import (
    get_connection_check_results,
    save_connection_check_result,
)
from app.services.crm import check_crm_connection
from app.services.panel_api import check_panel_api_connection
from app.services.system_diagnostics import (
    _alembic_head,
    backup_diagnostics,
    database_diagnostics,
    monitoring_diagnostics,
    safe_public_url,
    security_diagnostics,
)
from app.settings import settings


class SystemDiagnosticsUnitTests(unittest.TestCase):
    def test_database_unavailable_is_safe_and_does_not_echo_password(self):
        with patch(
            "app.services.system_diagnostics.get_engine",
            side_effect=RuntimeError(f"secret={settings.database_url}"),
        ):
            result = database_diagnostics()
        self.assertFalse(result["connected"])
        self.assertEqual(result["status"], "error")
        self.assertNotIn(settings.database_url, result["message"])
        if settings.crm_password:
            self.assertNotIn(settings.crm_password, str(result))

    def test_alembic_head_is_available_without_database_write(self):
        self.assertTrue(_alembic_head())

    def test_backup_is_neutral_on_windows(self):
        fake_os = SimpleNamespace(name="nt")
        with patch("app.services.system_diagnostics.os", fake_os):
            result = backup_diagnostics()
        self.assertEqual(result["status"], "muted")
        self.assertEqual(result["message"], "Недоступно в текущем окружении")

    def test_backup_timer_and_verified_dump_are_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            dump = Path(directory) / "key_writer_20260815.dump"
            dump.write_bytes(b"custom-format-placeholder")

            def command_result(command, timeout=2.0):
                joined = " ".join(command)
                if "is-enabled" in joined:
                    return "enabled"
                if "--property=Result" in joined:
                    return "success"
                if "ExecMainExitTimestamp" in joined:
                    return "Sat 2026-08-15 10:00:00 MSK"
                if "NextElapseUSecRealtime" in joined:
                    return "Sun 2026-08-16 02:00:00 MSK"
                return ""

            with (
                patch(
                    "app.services.system_diagnostics.os",
                    SimpleNamespace(name="posix"),
                ),
                patch("app.services.system_diagnostics.shutil.which", return_value="systemctl"),
                patch("app.services.system_diagnostics._safe_run", side_effect=command_result),
                patch("app.services.system_diagnostics.BACKUP_DIRECTORY", Path(directory)),
            ):
                result = backup_diagnostics()
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["timer_enabled"])
        self.assertTrue(result["last_success"])
        self.assertTrue(result["dump_verified"])
        self.assertEqual(result["count"], 1)

    def test_monitoring_fresh_and_stale_heartbeat(self):
        runtime = SimpleNamespace(
            panel_monitor_enabled=True,
            panel_monitor_interval_seconds=300,
            panel_monitor_concurrency=12,
            panel_monitor_stale_seconds=600,
            panel_manual_check_cooldown_seconds=10,
        )
        fresh = datetime.now(timezone.utc) - timedelta(seconds=5)
        stale = datetime.now(timezone.utc) - timedelta(seconds=900)
        base_state = {
            "status": "running",
            "finished_at": None,
            "total": 10,
            "completed": 4,
            "online": 3,
            "failed": 1,
            "active_panel_ids": [1, 2],
        }
        with (
            patch("app.services.system_diagnostics.get_monitor_runtime_settings", return_value=runtime),
            patch(
                "app.services.system_diagnostics.get_monitor_state",
                return_value={**base_state, "heartbeat_at": fresh},
            ),
        ):
            self.assertEqual(monitoring_diagnostics()["status"], "ok")
        with (
            patch("app.services.system_diagnostics.get_monitor_runtime_settings", return_value=runtime),
            patch(
                "app.services.system_diagnostics.get_monitor_state",
                return_value={**base_state, "heartbeat_at": stale},
            ),
        ):
            stale_result = monitoring_diagnostics()
        self.assertEqual(stale_result["status"], "warning")
        self.assertTrue(stale_result["heartbeat_stale"])

    def test_next_monitor_cycle_is_timezone_aware_and_after_last_cycle(self):
        runtime = SimpleNamespace(
            panel_monitor_enabled=True,
            panel_monitor_interval_seconds=300,
            panel_monitor_concurrency=12,
            panel_monitor_stale_seconds=600,
            panel_manual_check_cooldown_seconds=10,
        )
        finished_at = datetime(2026, 8, 20, 12, 0, tzinfo=timezone(timedelta(hours=3)))
        state = {
            "status": "completed", "finished_at": finished_at,
            "heartbeat_at": finished_at, "total": 1, "completed": 1,
            "online": 1, "failed": 0, "active_panel_ids": [],
        }
        with (
            patch("app.services.system_diagnostics.get_monitor_runtime_settings", return_value=runtime),
            patch("app.services.system_diagnostics.get_monitor_state", return_value=state),
        ):
            result = monitoring_diagnostics()
        self.assertEqual(result["last_cycle_at"], finished_at)
        self.assertGreater(result["next_cycle_at"], result["last_cycle_at"])
        self.assertEqual(result["next_cycle_at"].utcoffset(), finished_at.utcoffset())

    def test_production_http_and_cookie_warning(self):
        with (
            patch.object(settings, "app_environment", "production"),
            patch.object(settings, "session_https_only", False),
        ):
            result = security_diagnostics("http")
        self.assertEqual(result["status"], "warning")
        self.assertEqual(len(result["warnings"]), 2)

    def test_display_url_removes_credentials_query_and_fragment(self):
        self.assertEqual(
            safe_public_url("https://user:secret@example.test:8443/api/?token=hidden#x"),
            "https://example.test:8443/api",
        )

    def test_crm_success_and_timeout_are_safe(self):
        response = Mock(status_code=200, headers={"Content-Type": "application/json"}, text="")
        session = Mock()
        session.get.return_value = response
        with (
            patch("app.services.crm.crm_auth_configured", return_value=True),
            patch("app.services.crm._reset_session"),
            patch("app.services.crm._get_session", return_value=session),
        ):
            success = check_crm_connection()
        self.assertTrue(success["ok"])
        self.assertEqual(success["http_status"], 200)

        session.get.side_effect = requests.Timeout("password=do-not-show")
        with (
            patch("app.services.crm.crm_auth_configured", return_value=True),
            patch("app.services.crm._reset_session"),
            patch("app.services.crm._get_session", return_value=session),
        ):
            timeout = check_crm_connection()
        self.assertEqual(timeout["status"], "timeout")
        self.assertNotIn("do-not-show", str(timeout))

    def test_panel_safe_check_names_the_single_panel(self):
        panel = {"id": 17, "name": "Тестовая панель", "ip": "192.0.2.17"}
        with (
            patch("app.services.panel_api.panel_api_configured", return_value=True),
            patch("app.repositories.panel_repository.get_enabled_panels", return_value=[panel]),
            patch(
                "app.services.panel_api.check_panel",
                return_value={"status": "online", "response_time_ms": 42},
            ),
        ):
            result = check_panel_api_connection()
        self.assertTrue(result["ok"])
        self.assertEqual(result["panel_id"], 17)
        self.assertEqual(result["panel_name"], "Тестовая панель")
        self.assertEqual(result["response_time_ms"], 42)


class StoredConnectionDiagnosticsTests(PostgreSQLTestCase):
    def test_only_non_secret_connection_result_fields_are_persisted(self):
        with patch.object(settings, "crm_password", "known-crm-secret"):
            saved = save_connection_check_result(
                "crm",
                {
                    "ok": False,
                    "status": "timeout",
                    "message": "Сервис не ответил: known-crm-secret",
                    "response_time_ms": 1000,
                    "checked_at": "2026-08-15T10:00:00+00:00",
                    "password": "must-not-persist",
                    "cookie": "must-not-persist",
                    "token": "must-not-persist",
                },
                updated_by="Диагностика",
            )
        loaded = get_connection_check_results()["crm"]
        self.assertEqual(saved, loaded)
        self.assertNotIn("password", loaded)
        self.assertNotIn("cookie", loaded)
        self.assertNotIn("token", loaded)
        self.assertNotIn("must-not-persist", str(loaded))
        self.assertNotIn("known-crm-secret", str(loaded))


if __name__ == "__main__":
    unittest.main()
