import importlib
from unittest.mock import patch

from starlette.requests import Request

import app.db as database
from app.repositories import key_lifecycle_repository, key_repository, panel_repository
from app.services.key_lifecycle import release_key, reassign_key, replace_key
from app.services.audit import log_event
from app.services.writer import write_key_to_panels
from tests.postgres_test_case import PostgreSQLTestCase


class KeyLifecycleTests(PostgreSQLTestCase):
    @staticmethod
    def _request() -> Request:
        return Request({
            "type": "http", "method": "POST", "path": "/keys/test",
            "headers": [], "client": ("127.0.0.1", 50000),
            "session": {"user": {"login": "admin", "full_name": "Admin", "role": "admin"}},
        })

    def _key(self, number="9001", hex_value="AA009001") -> dict:
        type_id = key_repository.create_key_type("Lifecycle", "#159ED9")
        return key_repository.save_prepared_key(type_id, number, hex_value, "test")

    @staticmethod
    def _panel(suffix=1, address="Lifecycle 1") -> dict:
        mac = f"08:13:CD:30:00:{suffix:02X}"
        panel_repository.create_or_update_panel(address, f"Entrance {suffix}", mac=mac)
        with database.db() as conn:
            return dict(conn.execute("SELECT * FROM panels WHERE mac = ?", (mac,)).fetchone())

    @staticmethod
    def _success(message="ok"):
        return {"ok": True, "written": True, "status": "SUCCESS", "response": message}

    def _write(
        self, key, panels, *, address="Lifecycle 1", apartment="12",
        assignment_type="resident", assignment_policy="replace",
    ):
        with patch("app.services.writer.crm_add_key", return_value=self._success()):
            return write_key_to_panels(
                "message", key, panels, flat_num=apartment, address=address,
                request=self._request(), assignment_type=assignment_type,
                assignment_policy=assignment_policy,
                write_option=(
                    "add_selected_panels"
                    if assignment_policy == "preserve"
                    else "write_free_key"
                ),
            )

    def test_confirmed_write_is_current_state_not_audit_inference(self):
        key, panel = self._key(), self._panel()
        self._write(key, [panel])
        snapshot = key_lifecycle_repository.get_key_snapshot(key["id"])
        self.assertTrue(snapshot["occupied"])
        self.assertEqual([row["panel_id"] for row in snapshot["panels"]], [panel["id"]])
        with database.db() as conn:
            conn.execute("DELETE FROM operation_log WHERE key_id = ?", (key["id"],))
        self.assertEqual(
            key_repository.get_key_write_contexts([key["id"]])[key["id"]]["panel_ids"],
            [panel["id"]],
        )

    def test_release_deletes_externally_before_local_free(self):
        key, panel = self._key(), self._panel()
        self._write(key, [panel])
        with patch("app.services.key_lifecycle.crm_remove_key", return_value=self._success("removed")) as remove:
            result = release_key(key["id"], reason="test", request=self._request())
        self.assertTrue(result["ok"])
        remove.assert_called_once_with(panel["mac"], key["hex_value"], "12", 1)
        self.assertEqual(key_repository.get_key(key["id"])["status"], "free")
        self.assertFalse(key_lifecycle_repository.get_key_snapshot(key["id"])["occupied"])

    def test_partial_release_never_looks_successful_or_frees_locally(self):
        key, first, second = self._key(), self._panel(1), self._panel(2)
        self._write(key, [first, second])
        responses = [self._success("removed"), {"ok": False, "status": "TIMEOUT", "response": "timeout"}]
        with patch("app.services.key_lifecycle.crm_remove_key", side_effect=responses):
            result = release_key(key["id"], request=self._request())
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "PARTIAL")
        self.assertNotEqual(key_repository.get_key(key["id"])["status"], "free")
        snapshot = key_lifecycle_repository.get_key_snapshot(key["id"])
        self.assertEqual([row["panel_id"] for row in snapshot["panels"]], [second["id"]])

    def test_stale_release_operation_is_not_reused_for_another_current_panel(self):
        key, first, second = self._key(), self._panel(1), self._panel(2)
        self._write(key, [first])
        with patch("app.services.key_lifecycle.crm_remove_key", return_value={
            "ok": False, "status": "TIMEOUT", "response": "timeout",
        }):
            stale = release_key(key["id"], reason="first attempt", request=self._request())
        self.assertFalse(stale["ok"])

        # The authoritative state changed after that attempt: the former panel
        # is confirmed absent and another panel is now active.  The incomplete
        # operation must not be resumed merely because key_id/type match.
        key_lifecycle_repository.record_panel_result(
            key_id=key["id"], panel_id=first["id"], operation="delete",
            status="SUCCESS", success=True,
        )
        key_lifecycle_repository.record_panel_result(
            key_id=key["id"], panel_id=second["id"], operation="write",
            status="SUCCESS", success=True, flat_num="12",
        )
        with patch(
            "app.services.key_lifecycle.crm_remove_key",
            return_value=self._success("removed"),
        ) as remove:
            current = release_key(
                key["id"], reason="current attempt", request=self._request(),
            )

        self.assertTrue(current["ok"])
        self.assertNotEqual(current["operation_id"], stale["operation_id"])
        remove.assert_called_once_with(second["mac"], key["hex_value"], "12", 1)
        abandoned = key_lifecycle_repository.get_operation(stale["operation_id"])
        self.assertEqual(abandoned["status"], "completed")
        self.assertIn("текущее назначение или набор панелей изменился", abandoned["last_error"])

    def test_idempotent_absence_allows_release(self):
        key, panel = self._key(), self._panel()
        self._write(key, [panel])
        with patch("app.services.key_lifecycle.crm_remove_key", return_value={
            "ok": False, "status": "ALREADY_ABSENT", "response": "not found"
        }):
            result = release_key(key["id"], request=self._request())
        self.assertTrue(result["ok"])
        self.assertEqual(key_repository.get_key(key["id"])["status"], "free")

    def test_release_uses_one_crm_delete_per_confirmed_panel(self):
        key, panel = self._key(), self._panel()
        self._write(key, [panel])
        # Reproduce data written by the former local-only assignment editor:
        # the panel still has flat 12, while the current local assignment says 13.
        key_repository.set_key_assignment(
            key["id"], "resident", address="Lifecycle 1", apartment="13",
            assigned_by="legacy edit",
        )
        with patch(
            "app.services.key_lifecycle.crm_remove_key",
            return_value={"ok": True, "status": "ALREADY_ABSENT", "response": "not found"},
        ) as remove:
            result = release_key(key["id"], request=self._request())

        self.assertTrue(result["ok"])
        self.assertEqual(remove.call_count, 1)
        self.assertEqual(remove.call_args.args[0], panel["mac"])
        self.assertEqual(remove.call_args.args[1], key["hex_value"])
        self.assertEqual(key_repository.get_key(key["id"])["status"], "free")

    def test_reassign_deletes_old_access_before_writing_target(self):
        key, old_panel, new_panel = self._key(), self._panel(1), self._panel(2)
        self._write(key, [old_panel])
        calls = []

        def write_target(_snapshot, pending_ids):
            calls.append(("write", pending_ids))
            return self._write(
                key_repository.get_key(key["id"]), [new_panel],
                address="Lifecycle 2", apartment="8",
            )

        with patch(
            "app.services.key_lifecycle.crm_remove_key",
            side_effect=lambda *args: calls.append(("delete", args[0])) or self._success("removed"),
        ):
            result = reassign_key(
                key["id"], write_callback=write_target,
                reason="Новый адрес, кв. 8", request=self._request(),
                target_context={
                    "address": "Lifecycle 2", "apartment": "8",
                    "panel_ids": [new_panel["id"]],
                },
            )

        self.assertTrue(result["ok"])
        self.assertEqual(calls[0], ("delete", old_panel["mac"]))
        self.assertEqual(calls[1], ("write", [new_panel["id"]]))
        context = key_repository.get_key_write_contexts([key["id"]])[key["id"]]
        self.assertEqual(context["panel_ids"], [new_panel["id"]])

    def test_reassign_never_writes_when_old_delete_fails(self):
        key, panel = self._key(), self._panel()
        self._write(key, [panel])
        callback = []
        with patch("app.services.key_lifecycle.crm_remove_key", return_value={
            "ok": False, "status": "TIMEOUT", "response": "timeout",
        }):
            result = reassign_key(
                key["id"], write_callback=lambda snapshot, panel_ids: callback.append((snapshot, panel_ids)),
                reason="Новый адрес", request=self._request(),
                target_context={"panel_ids": [panel["id"]]},
            )
        self.assertFalse(result["ok"])
        self.assertEqual(callback, [])
        self.assertNotEqual(key_repository.get_key(key["id"])["status"], "free")

    def test_replace_passes_exact_old_snapshot_and_stops_on_delete_error(self):
        old, panel = self._key("9002", "AA009002"), self._panel()
        self._write(old, [panel])
        type_id = old["key_type_id"]
        new = key_repository.save_prepared_key(type_id, "9003", "AA009003", "test")
        callback_calls = []
        with patch("app.services.key_lifecycle.crm_remove_key", return_value={
            "ok": False, "status": "ERROR", "response": "denied"
        }):
            result = replace_key(
                old["id"], new, final_old_status="defective", reason="replacement",
                request=self._request(),
                write_callback=lambda key, snapshot: callback_calls.append((key, snapshot)),
            )
        self.assertFalse(result["ok"])
        self.assertEqual(callback_calls, [])
        self.assertEqual(result["release"]["snapshot"]["panels"][0]["panel_id"], panel["id"])

    def test_replace_resumes_only_unfinished_write_after_restart(self):
        old = self._key("9010", "AA009010")
        panels = [self._panel(index) for index in (1, 2, 3)]
        self._write(old, panels)
        new = key_repository.save_prepared_key(
            old["key_type_id"], "9011", "AA009011", "test"
        )
        first_write_panel_ids = []

        def partial_write(_new_key, snapshot):
            panel_ids = [int(panel["panel_id"]) for panel in snapshot["panels"]]
            first_write_panel_ids.extend(panel_ids)
            return [
                {
                    "panel": {"id": panel_id},
                    "written": panel_id != panels[2]["id"],
                    "status": "SUCCESS" if panel_id != panels[2]["id"] else "TIMEOUT",
                    "response": "ok" if panel_id != panels[2]["id"] else "timeout",
                }
                for panel_id in panel_ids
            ]

        with patch(
            "app.services.key_lifecycle.crm_remove_key",
            return_value=self._success("removed"),
        ) as remove:
            first = replace_key(
                old["id"], new, final_old_status="defective",
                reason="replace after failure", request=self._request(),
                write_callback=partial_write,
            )

        self.assertFalse(first["ok"])
        self.assertEqual(first["status"], "PARTIAL")
        self.assertEqual(first_write_panel_ids, [panel["id"] for panel in panels])
        self.assertEqual(remove.call_count, 3)

        persisted = key_lifecycle_repository.get_operation(first["operation_id"])
        self.assertEqual(persisted["operation_type"], "replace")
        self.assertEqual(persisted["old_key_id"], old["id"])
        self.assertEqual(persisted["new_key_id"], new["id"])
        self.assertEqual(persisted["reason"], "replace after failure")
        self.assertEqual(persisted["source_panel_ids"], [panel["id"] for panel in panels])
        self.assertEqual(
            [panel["panel_id"] for panel in persisted["assignment_snapshot"]["panels"]],
            [panel["id"] for panel in panels],
        )
        delete_steps = [step for step in persisted["steps"] if step["phase"] == "delete_old"]
        write_steps = [step for step in persisted["steps"] if step["phase"] == "write_new"]
        self.assertTrue(all(step["state"] == "success" for step in delete_steps))
        self.assertEqual(
            [step["state"] for step in write_steps],
            ["success", "success", "error"],
        )

        # A module reload represents a new application process: only PostgreSQL
        # state survives and must be sufficient to resume the operation.
        import app.services.key_lifecycle as lifecycle_service
        lifecycle_service = importlib.reload(lifecycle_service)
        retried_panel_ids = []

        def successful_retry(_new_key, snapshot):
            panel_ids = [int(panel["panel_id"]) for panel in snapshot["panels"]]
            retried_panel_ids.extend(panel_ids)
            return [
                {
                    "panel": {"id": panel_id},
                    "written": True,
                    "status": "SUCCESS",
                    "response": "ok",
                }
                for panel_id in panel_ids
            ]

        with patch(
            "app.services.key_lifecycle.crm_remove_key",
            side_effect=AssertionError("completed delete steps must not be retried"),
        ):
            second = lifecycle_service.replace_key(
                old["id"], new, final_old_status="defective",
                reason="replace after failure", request=self._request(),
                write_callback=successful_retry,
            )

        self.assertTrue(second["ok"])
        self.assertEqual(retried_panel_ids, [panels[2]["id"]])
        persisted = key_lifecycle_repository.get_operation(first["operation_id"])
        self.assertEqual(persisted["status"], "completed")
        write_steps = [step for step in persisted["steps"] if step["phase"] == "write_new"]
        self.assertEqual([step["attempts"] for step in write_steps], [1, 1, 2])
        self.assertTrue(all(step["state"] == "success" for step in write_steps))

    def test_closed_history_does_not_make_key_occupied(self):
        key, panel = self._key(), self._panel()
        key_lifecycle_repository.record_panel_result(
            key_id=key["id"], panel_id=panel["id"], operation="delete",
            status="SUCCESS", success=True,
        )
        log_event(
            request=self._request(), action="legacy_write", status="SUCCESS",
            key_id=key["id"], panel_id=panel["id"], hex_value=key["hex_value"],
        )
        self.assertFalse(key_lifecycle_repository.get_key_snapshot(key["id"])["occupied"])
        self.assertEqual(key_repository.get_key_write_contexts([key["id"]])[key["id"]]["panel_ids"], [])

    def test_unknown_reconciliation_state_is_not_treated_as_current_access(self):
        key, panel = self._key(), self._panel()
        # Historical success can only be migrated as an uncertain observation.
        # It is not proof that the key is currently programmed on this panel.
        with database.db() as conn:
            conn.execute(
                """
                INSERT INTO key_panel_states(
                    key_id, panel_id, state, flat_num, is_inner,
                    last_operation, last_status, last_error
                ) VALUES (?, ?, 'unknown', '12', 1, 'write', 'SUCCESS',
                          'Требуется сверка текущего состояния')
                """,
                (key["id"], panel["id"]),
            )

        snapshot = key_lifecycle_repository.get_key_snapshot(key["id"])
        self.assertEqual(snapshot["panels"], [])
        self.assertFalse(snapshot["occupied"])
        self.assertEqual(
            key_repository.get_key_write_contexts([key["id"]])[key["id"]]["panel_ids"],
            [],
        )

        with patch(
            "app.services.key_lifecycle.crm_remove_key",
            side_effect=AssertionError("unknown state must not trigger CRM delete"),
        ) as remove:
            released = release_key(key["id"], request=self._request())

        self.assertTrue(released["ok"])
        remove.assert_not_called()
        self.assertEqual(key_repository.get_key(key["id"])["status"], "free")

    def test_resident_add_access_preserves_both_addresses(self):
        key = self._key("9101", "AA009101")
        first = self._panel(1, "Prosveshcheniya 148")
        second = self._panel(2, "Lenina 296")
        self._write(
            key, [first], address="Prosveshcheniya 148", apartment="3",
        )
        self._write(
            key_repository.get_key(key["id"]), [second],
            address="Lenina 296", apartment="44",
            assignment_policy="preserve",
        )

        snapshot = key_lifecycle_repository.get_key_snapshot(key["id"])
        active = {
            (item["address"], item["apartment"]): {
                panel["panel_id"] for panel in snapshot["panels"]
                if panel.get("access_id") == item["id"]
            }
            for item in snapshot["accesses"] if item["active"]
        }
        self.assertEqual(active[("Prosveshcheniya 148", "3")], {first["id"]})
        self.assertEqual(active[("Lenina 296", "44")], {second["id"]})

    def test_resident_reassign_closes_old_and_activates_new_address(self):
        key = self._key("9102", "AA009102")
        old_panel = self._panel(3, "Prosveshcheniya 148")
        new_panel = self._panel(4, "Lenina 296")
        self._write(
            key, [old_panel], address="Prosveshcheniya 148", apartment="3",
        )

        def write_target(_snapshot, pending_ids):
            self.assertEqual(pending_ids, [new_panel["id"]])
            return self._write(
                key_repository.get_key(key["id"]), [new_panel],
                address="Lenina 296", apartment="44",
            )

        with patch(
            "app.services.key_lifecycle.crm_remove_key",
            return_value=self._success("removed"),
        ):
            result = reassign_key(
                key["id"], write_callback=write_target,
                reason="resident move", request=self._request(),
                target_context={
                    "address": "Lenina 296", "apartment": "44",
                    "panel_ids": [new_panel["id"]],
                },
            )

        self.assertTrue(result["ok"])
        snapshot = key_lifecycle_repository.get_key_snapshot(key["id"])
        self.assertEqual(
            [(item["address"], item["apartment"]) for item in snapshot["accesses"]],
            [("Lenina 296", "44")],
        )
        self.assertEqual([item["panel_id"] for item in snapshot["panels"]], [new_panel["id"]])

    def test_replace_key_inherits_every_active_resident_access(self):
        old = self._key("9103", "AA009103")
        first = self._panel(5, "Prosveshcheniya 148")
        second = self._panel(6, "Lenina 296")
        self._write(old, [first], address="Prosveshcheniya 148", apartment="3")
        self._write(
            key_repository.get_key(old["id"]), [second],
            address="Lenina 296", apartment="44", assignment_policy="preserve",
        )
        new = key_repository.save_prepared_key(
            old["key_type_id"], "9104", "AA009104", "test",
        )

        def write_replacement(new_key, snapshot):
            values = []
            for panel_row in snapshot["panels"]:
                panel = panel_repository.get_panels_by_ids(
                    [int(panel_row["panel_id"])]
                )[0]
                values.extend(self._write(
                    new_key, [panel], address=panel_row["address"],
                    apartment=panel_row["flat_num"], assignment_policy="preserve",
                ))
            return values

        with patch(
            "app.services.key_lifecycle.crm_remove_key",
            return_value=self._success("removed"),
        ):
            result = replace_key(
                old["id"], new, final_old_status="defective",
                reason="broken key", request=self._request(),
                write_callback=write_replacement,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(key_repository.get_key(old["id"])["status"], "defective")
        snapshot = key_lifecycle_repository.get_key_snapshot(new["id"])
        self.assertEqual(
            {(item["address"], item["apartment"]) for item in snapshot["accesses"]},
            {("Prosveshcheniya 148", "3"), ("Lenina 296", "44")},
        )
        self.assertEqual(
            {item["panel_id"] for item in snapshot["panels"]},
            {first["id"], second["id"]},
        )

    def test_service_key_adds_51st_panel_without_reassign(self):
        key = self._key("9105", "AA009105")
        panels = [self._panel(index, "Service estate") for index in range(1, 52)]
        self._write(
            key, panels[:50], address="Service estate", apartment="",
            assignment_type="employee", assignment_policy="preserve",
        )
        self._write(
            key_repository.get_key(key["id"]), [panels[50]],
            address="Service estate", apartment="",
            assignment_type="employee", assignment_policy="preserve",
        )
        snapshot = key_lifecycle_repository.get_key_snapshot(key["id"])
        self.assertEqual(len(snapshot["panels"]), 51)
        self.assertEqual(len(snapshot["accesses"]), 1)
        self.assertEqual(snapshot["accesses"][0]["access_type"], "service")
