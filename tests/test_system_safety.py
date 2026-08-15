from unittest.mock import patch

import requests

from starlette.requests import Request

from tests.postgres_test_case import PostgreSQLTestCase

import app.db as database
from app.routers.manual_write import manual_write_execute, manual_write_preview
from app.repositories import key_repository, panel_repository
from app.services.auth import hash_password, verify_password
from app.services.writer import write_key_to_panels


class SystemSafetyTests(PostgreSQLTestCase):
    def setUp(self):
        super().setUp()

    @staticmethod
    def _request(path: str, training: bool = False) -> Request:
        return Request(
            {
                "type": "http",
                "method": "POST",
                "path": path,
                "query_string": b"",
                "headers": [],
                "client": ("127.0.0.1", 50000),
                "session": {
                    "training_mode": training,
                    "user": {
                        "id": 1,
                        "login": "admin",
                        "full_name": "Администратор",
                        "role": "admin",
                    },
                },
            }
        )

    def test_training_write_never_calls_crm_or_changes_database(self):
        request = self._request("/write/manual/write", training=True)
        key = {
            "id": 999,
            "number": "100",
            "hex_value": "AABBCCDD",
            "status": "free",
        }
        panels = [
            {
                "id": 20,
                "address": "Тестовая 1",
                "name": "Подъезд 1",
                "mac": "08:13:CD:00:00:01",
            }
        ]
        with patch("app.services.writer.crm_add_key") as crm:
            results = write_key_to_panels(
                "resident_manual",
                key,
                panels,
                flat_num="7",
                address="Тестовая 1",
                request=request,
            )
        crm.assert_not_called()
        self.assertEqual(results[0]["status"], "TRAINING_MODE")
        with database.db() as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM operation_log").fetchone()[0],
                0,
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM key_assignments").fetchone()[0],
                0,
            )

    def test_manual_write_does_not_restore_panels_after_empty_selection(self):
        request = self._request("/write/manual/write")
        key = {
            "id": 1,
            "number": "100",
            "hex_value": "AABBCCDD",
            "status": "free",
        }
        with (
            patch("app.routers.manual_write.find_key", return_value=key),
            patch("app.routers.manual_write.get_panels", return_value=[]) as panels,
            patch("app.routers.manual_write.get_key_write_context", return_value={}),
            patch("app.routers.manual_write.find_panels_by_address") as fallback,
            patch("app.routers.manual_write.write_key_to_panels") as writer,
        ):
            response = manual_write_execute(
                request=request,
                key_query="100",
                address="Тестовая 1",
                apartment="7",
                inner=1,
                panel_ids=[],
                key_type_id=0,
            )
        panels.assert_not_called()
        fallback.assert_not_called()
        writer.assert_not_called()
        self.assertIn("Не выбрана ни одна панель", response.body.decode("utf-8"))

    def test_manual_write_preview_matches_padded_key_number(self):
        key_type_id = key_repository.create_key_type("Оранжевый", "#FF982A")
        key = key_repository.save_prepared_key(
            key_type_id, "000050", "AA000050", "Тест"
        )
        panel_repository.create_or_update_panel(
            address="ул. Тестовая 50",
            entrance="подъезд 1",
            mac="08:13:CD:00:00:50",
        )

        response = manual_write_preview(
            request=self._request("/write/manual/preview"),
            key_query="50",
            address="ул. Тестовая 50",
            apartment="5",
            key_type_id=key_type_id,
        )

        body = response.body.decode("utf-8")
        self.assertIn(f"Ключ №{key['number']}", body)
        self.assertNotIn("Ключ не найден в базе", body)

    def test_manual_write_keeps_assignment_address_and_tracks_panel_sources(self):
        request = self._request("/write/manual/write")
        key = {"id": 1, "number": "973", "hex_value": "AABBCCDD", "status": "free"}
        panels = [
            {"id": 10, "address": "ул. Ясногорская 16/2", "mac": "08:13:CD:00:00:10"},
            {"id": 11, "address": "ул. Ясногорская 16/2", "mac": "08:13:CD:00:00:11"},
            {"id": 20, "address": "ул. Роз 6/6А", "mac": "08:13:CD:00:00:20"},
            {"id": 21, "address": "ул. Роз 6/6А", "mac": "08:13:CD:00:00:21"},
        ]
        with (
            patch("app.routers.manual_write.find_key", return_value=key),
            patch("app.routers.manual_write.get_panels", return_value=panels),
            patch("app.routers.manual_write.get_key_write_context", return_value={"is_used": False, "panel_ids": []}),
            patch("app.routers.manual_write.write_key_to_panels", return_value=[]) as writer,
        ):
            manual_write_execute(
                request=request,
                key_query="973",
                address="ул. Ясногорская 16/2",
                apartment="4",
                inner=1,
                panel_ids=[10, 11, 20, 21],
                automatic_panel_ids=[10, 11],
                manual_panel_ids=[20, 21, 20],
                key_type_id=0,
            )
        kwargs = writer.call_args.kwargs
        self.assertEqual(kwargs["address"], "ул. Ясногорская 16/2")
        self.assertEqual(kwargs["automatic_panel_ids"], {10, 11})
        self.assertEqual(kwargs["manual_panel_ids"], {20, 21})

    def test_manual_write_occupied_key_requires_operator_choice(self):
        request = self._request("/write/manual/write")
        key = {"id": 5, "number": "408", "hex_value": "FB44EDD7", "status": "issued_resident"}
        panels = [{"id": 12, "address": "Новый дом 2", "mac": "08:13:CD:00:00:12"}]
        context = {
            "is_used": True, "assignment_type_name": "Жилец",
            "assignment_address": "Старый дом 1", "assignment_apartment": "4",
            "panel_ids": [9],
        }
        with (
            patch("app.routers.manual_write.find_key", return_value=key),
            patch("app.routers.manual_write.get_panels", return_value=panels),
            patch("app.routers.manual_write.get_key_write_context", return_value=context),
            patch("app.routers.manual_write.write_key_to_panels") as writer,
        ):
            response = manual_write_execute(
                request=request, key_query="408", address="Новый дом 2", apartment="8",
                inner=1, panel_ids=[12], key_type_id=0, occupied_action="",
            )
        writer.assert_not_called()
        self.assertIn("Ключ уже используется", response.body.decode("utf-8"))

    def test_manual_write_reassigns_through_shared_decision(self):
        request = self._request("/write/manual/write")
        key = {"id": 5, "number": "408", "hex_value": "FB44EDD7", "status": "issued_resident"}
        panels = [{"id": 12, "address": "Новый дом 2", "mac": "08:13:CD:00:00:12"}]
        context = {
            "is_used": True, "assignment_type_name": "Жилец",
            "assignment_address": "Старый дом 1", "assignment_apartment": "4",
            "panel_ids": [9],
        }
        with (
            patch("app.routers.manual_write.find_key", return_value=key),
            patch("app.routers.manual_write.get_panels", return_value=panels),
            patch("app.routers.manual_write.get_key_write_context", return_value=context),
            patch("app.routers.manual_write.write_key_to_panels", return_value=[]) as writer,
        ):
            manual_write_execute(
                request=request, key_query="408", address="Новый дом 2", apartment="8",
                inner=1, panel_ids=[12], key_type_id=0, occupied_action="reassign",
            )
        kwargs = writer.call_args.kwargs
        self.assertEqual(kwargs["assignment_policy"], "replace")
        self.assertEqual(kwargs["write_option"], "reassign_to_new_address")
        self.assertEqual(kwargs["known_panel_ids"], {9})

    def test_manual_write_adds_panels_without_changing_assignment(self):
        request = self._request("/write/manual/write")
        key = {"id": 5, "number": "408", "hex_value": "FB44EDD7", "status": "issued_resident"}
        panels = [{"id": 12, "address": "Новый дом 2", "mac": "08:13:CD:00:00:12"}]
        context = {"is_used": True, "assignment_type_name": "Жилец", "panel_ids": [9]}
        with (
            patch("app.routers.manual_write.find_key", return_value=key),
            patch("app.routers.manual_write.get_panels", return_value=panels),
            patch("app.routers.manual_write.get_key_write_context", return_value=context),
            patch("app.routers.manual_write.write_key_to_panels", return_value=[]) as writer,
        ):
            manual_write_execute(
                request=request, key_query="408", address="Новый дом 2", apartment="8",
                inner=1, panel_ids=[12], key_type_id=0, occupied_action="add_panels",
            )
        kwargs = writer.call_args.kwargs
        self.assertEqual(kwargs["assignment_policy"], "preserve")
        self.assertEqual(kwargs["write_option"], "add_selected_panels")
        self.assertEqual(kwargs["known_panel_ids"], {9})

    def test_partial_panel_write_keeps_success_and_reports_each_failure(self):
        key = {
            "id": 999,
            "number": "100",
            "hex_value": "AABBCCDD",
            "status": "free",
            "type_name": "Синий",
        }
        panels = [
            {"id": 20, "name": "Подъезд 1", "mac": "08:13:CD:00:00:01"},
            {"id": 21, "name": "Подъезд 2", "mac": "08:13:CD:00:00:02"},
            {"id": 22, "name": "Подъезд 3", "mac": "08:13:CD:00:00:03"},
        ]
        success = {
            "ok": True,
            "written": True,
            "status": "SUCCESS",
            "response": "Ключ успешно записан",
            "message": "Ключ успешно записан",
        }
        auth_error = {
            "ok": False,
            "written": False,
            "status": "AUTH_REQUIRED",
            "response": "Ошибка авторизации CRM",
            "message": "Ошибка авторизации CRM",
        }

        with patch(
            "app.services.writer.crm_add_key",
            side_effect=[success, requests.Timeout(), auth_error],
        ) as crm_add_key:
            results = write_key_to_panels(
                "partial_test",
                key,
                panels,
                flat_num="7",
                address="Тестовая 1",
                request=self._request("/message/write"),
            )

        self.assertEqual(crm_add_key.call_count, 3)
        self.assertEqual(
            [result["status"] for result in results],
            ["SUCCESS", "TIMEOUT", "AUTH_REQUIRED"],
        )
        self.assertEqual(
            [result["written"] for result in results],
            [True, False, False],
        )
        self.assertTrue(all(result["persisted"] for result in results))
        with database.db() as conn:
            stored = conn.execute(
                """
                SELECT panel_id, status
                FROM operation_log
                WHERE mode = 'partial_test'
                ORDER BY panel_id
                """
            ).fetchall()
        self.assertEqual(
            [(row["panel_id"], row["status"]) for row in stored],
            [(20, "SUCCESS"), (21, "TIMEOUT"), (22, "AUTH_REQUIRED")],
        )

    def test_invalid_panel_response_does_not_stop_remaining_panels(self):
        key = {
            "id": 999,
            "number": "101",
            "hex_value": "AABBCCDE",
            "status": "free",
        }
        panels = [
            {"id": 30, "name": "Подъезд 1", "mac": "08:13:CD:00:00:04"},
            {"id": 31, "name": "Подъезд 2", "mac": "08:13:CD:00:00:05"},
        ]
        success = {
            "ok": True,
            "written": True,
            "status": "SUCCESS",
            "response": "Ключ успешно записан",
            "message": "Ключ успешно записан",
        }

        with patch(
            "app.services.writer.crm_add_key",
            side_effect=[None, success],
        ):
            results = write_key_to_panels(
                "invalid_response_test",
                key,
                panels,
                request=self._request("/message/write"),
            )

        self.assertEqual([item["status"] for item in results], ["ERROR", "SUCCESS"])

    def test_passwords_are_salted_and_legacy_passwords_still_verify(self):
        first = hash_password("strong-password")
        second = hash_password("strong-password")
        self.assertNotEqual(first, second)
        self.assertTrue(verify_password("strong-password", first))
        self.assertFalse(verify_password("wrong", first))
        self.assertTrue(verify_password("legacy", "legacy"))

if __name__ == "__main__":
    unittest.main()
