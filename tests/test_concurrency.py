from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from fastapi.testclient import TestClient

from tests.postgres_test_case import PostgreSQLTestCase

import app.db as database
from app.main import app
from app.repositories import employee_repository, key_repository, panel_repository
from app.services.writer import write_key_to_panels


class ConcurrentMutationTests(PostgreSQLTestCase):
    def setUp(self):
        super().setUp()
        self.key_type_id = key_repository.create_key_type("Concurrency", "#159ED9")

    def _key(self, number: str, hex_value: str) -> dict:
        return key_repository.save_prepared_key(
            self.key_type_id,
            number,
            hex_value,
            "Concurrency test",
        )

    def test_same_free_key_cannot_be_issued_to_two_employees(self):
        key = self._key("1001", "AACCEE01")
        employee_ids = [
            employee_repository.create_employee("Concurrent Employee A"),
            employee_repository.create_employee("Concurrent Employee B"),
        ]
        barrier = Barrier(2)

        def issue(employee_id: int) -> str:
            barrier.wait(timeout=5)
            try:
                employee_repository.issue_key_to_employee(employee_id, key["id"])
                return "issued"
            except ValueError:
                return "rejected"

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(issue, employee_ids))

        self.assertCountEqual(outcomes, ["issued", "rejected"])
        with database.db() as connection:
            rows = connection.execute(
                """
                SELECT employee_id
                FROM employee_keys
                WHERE key_id = ? AND status = 'active'
                """,
                (key["id"],),
            ).fetchall()
        self.assertEqual(len(rows), 1)

    def test_nonempty_hex_is_globally_unique_during_parallel_creation(self):
        barrier = Barrier(2)

        def create(number: str) -> str:
            barrier.wait(timeout=5)
            try:
                self._key(number, "AACCEE02")
                return "created"
            except ValueError:
                return "rejected"

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(create, ["1002", "1003"]))

        self.assertCountEqual(outcomes, ["created", "rejected"])
        with database.db() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM keys WHERE UPPER(hex_value) = 'AACCEE02'"
            ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_parallel_edit_of_same_key_is_serialized_without_partial_state(self):
        key = self._key("1005", "AACCEE05")
        barrier = Barrier(2)

        def edit(note: str) -> str:
            barrier.wait(timeout=5)
            key_repository.update_key(
                key["id"],
                self.key_type_id,
                "1005",
                "AACCEE05",
                note,
            )
            return "saved"

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(edit, ["Edit A", "Edit B"]))

        self.assertEqual(outcomes, ["saved", "saved"])
        stored = key_repository.get_key(key["id"])
        self.assertIsNotNone(stored)
        self.assertEqual(stored["number"], "1005")
        self.assertEqual(stored["hex_value"], "AACCEE05")
        self.assertIn(stored["note"], {"Edit A", "Edit B"})

    def test_parallel_write_of_same_key_calls_panel_once(self):
        key = self._key("1004", "AACCEE04")
        panel_repository.create_or_update_panel(
            "Concurrency street 1",
            "Entrance 1",
            mac="08:13:CD:00:EE:04",
        )
        with database.db() as connection:
            panel = dict(
                connection.execute(
                    "SELECT * FROM panels WHERE mac = '08:13:CD:00:EE:04'"
                ).fetchone()
            )
        barrier = Barrier(2)

        def write() -> str:
            barrier.wait(timeout=5)
            result = write_key_to_panels(
                "concurrency_test",
                key,
                [panel],
                assignment_policy="preserve",
            )
            return result[0]["status"]

        success = {
            "ok": True,
            "written": True,
            "status": "SUCCESS",
            "response": "written",
            "message": "written",
        }
        with patch("app.services.writer.crm_add_key", return_value=success) as crm:
            with ThreadPoolExecutor(max_workers=2) as executor:
                statuses = list(executor.map(lambda _: write(), range(2)))

        self.assertEqual(crm.call_count, 1)
        self.assertCountEqual(statuses, ["SUCCESS", "ALREADY_ON_PANEL"])

    def test_health_endpoint_handles_parallel_requests_with_bounded_pool(self):
        with TestClient(app) as client:
            with ThreadPoolExecutor(max_workers=12) as executor:
                responses = list(executor.map(lambda _: client.get("/healthz"), range(24)))
        self.assertTrue(all(response.status_code == 200 for response in responses))
        self.assertTrue(all(response.json() == {"status": "ok"} for response in responses))
