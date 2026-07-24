import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from starlette.requests import Request

import app.db as database
from app.routers.manual_write import manual_write_execute
from app.services.auth import hash_password, verify_password
from app.services.writer import write_key_to_panels


class SystemSafetyTests(unittest.TestCase):
    def setUp(self):
        self._original_db_path = database.DB_PATH
        self._temporary_directory = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self._temporary_directory.name) / "test.db"
        database.init_db()

    def tearDown(self):
        database.DB_PATH = self._original_db_path
        self._temporary_directory.cleanup()

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

    def test_passwords_are_salted_and_legacy_passwords_still_verify(self):
        first = hash_password("strong-password")
        second = hash_password("strong-password")
        self.assertNotEqual(first, second)
        self.assertTrue(verify_password("strong-password", first))
        self.assertFalse(verify_password("wrong", first))
        self.assertTrue(verify_password("legacy", "legacy"))

if __name__ == "__main__":
    unittest.main()
