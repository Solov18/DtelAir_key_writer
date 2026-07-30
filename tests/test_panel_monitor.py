import threading
import time

from tests.postgres_test_case import PostgreSQLTestCase

from app.repositories import panel_repository
from app.repositories.panel_monitor_repository import (
    begin_cycle_if_due,
    get_monitor_state,
    request_monitor_cycle,
)
from app.repositories.system_settings_repository import (
    save_monitor_runtime_settings,
)
from app.services.panel_monitor import run_monitor_cycle


class PanelMonitorTests(PostgreSQLTestCase):
    def _create_panels(self, count: int) -> list[dict]:
        items = []
        for index in range(count):
            panel_repository.create_or_update_panel(
                address=f"Тестовый дом {index // 4}",
                entrance=f"Вход {index}",
                mac=f"08:13:CD:10:{index // 256:02X}:{index % 256:02X}",
                ip=f"10.0.{index // 250}.{index % 250 + 1}",
            )
        return panel_repository.get_all_panels()

    def test_repeated_requests_share_one_persistent_job(self):
        first, first_created = request_monitor_cycle("Первый оператор")
        second, second_created = request_monitor_cycle("Второй оператор")
        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(first["status"], "queued")
        self.assertEqual(second["status"], "queued")
        claimed = begin_cycle_if_due(300)
        self.assertIsNotNone(claimed)
        self.assertIsNone(begin_cycle_if_due(300))

    def test_full_cycle_limits_parallelism_skips_disabled_and_survives_error(self):
        panels = self._create_panels(24)
        panel_repository.set_panel_enabled(panels[-1]["id"], False)
        save_monitor_runtime_settings(
            {
                "panel_monitor_enabled": True,
                "panel_monitor_interval_seconds": 300,
                "panel_monitor_concurrency": 4,
                "panel_monitor_stale_seconds": 600,
                "panel_manual_check_cooldown_seconds": 1,
            },
            updated_by="Тест",
        )
        request_monitor_cycle("Тест")
        self.assertIsNotNone(begin_cycle_if_due(300))

        guard = threading.Lock()
        active = 0
        maximum = 0

        def checker(panel):
            nonlocal active, maximum
            with guard:
                active += 1
                maximum = max(maximum, active)
            try:
                time.sleep(0.01)
                if panel["id"] == panels[4]["id"]:
                    raise RuntimeError("mock failure")
                return {
                    "status": "online",
                    "temperature": 42.5,
                    "supply_voltage": 13.0,
                    "firmware_version": "test-1",
                    "uptime_seconds": 3600,
                    "last_error": "",
                }
            finally:
                with guard:
                    active -= 1

        # No explicit concurrency is passed: the cycle must read the value
        # saved in PostgreSQL immediately before it starts.
        result = run_monitor_cycle(checker=checker)
        self.assertEqual(result["total"], 23)
        self.assertEqual(result["completed"], 23)
        self.assertEqual(result["online"], 22)
        self.assertEqual(result["failed"], 1)
        self.assertLessEqual(maximum, 4)
        self.assertGreater(maximum, 1)

        state = get_monitor_state()
        self.assertEqual(state["status"], "completed")
        self.assertEqual(state["completed"], 23)
        self.assertEqual(state["active_panel_ids"], [])
        self.assertEqual(
            panel_repository.get_panel_by_id(panels[4]["id"])["network_status"],
            "error",
        )
        self.assertEqual(
            panel_repository.get_panel_by_id(panels[-1]["id"])["network_status"],
            "disabled",
        )
