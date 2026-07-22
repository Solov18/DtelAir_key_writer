import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

import app.db as database
from app.repositories import panel_repository
from app.services import panel_api


class PanelRepositoryTests(unittest.TestCase):
    def setUp(self):
        self._original_db_path = database.DB_PATH
        self._temporary_directory = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self._temporary_directory.name) / "test.db"
        database.init_db()

    def tearDown(self):
        database.DB_PATH = self._original_db_path
        self._temporary_directory.cleanup()

    def _create(self, address, entrance, mac, ip=""):
        panel_repository.create_or_update_panel(
            address=address,
            entrance=entrance,
            mac=mac,
            ip=ip,
        )
        normalized_mac = panel_repository.normalize_mac(mac)
        return next(
            panel
            for panel in panel_repository.get_all_panels()
            if panel["mac"] == normalized_mac
        )

    def test_server_filters_pagination_and_status_statistics(self):
        first = self._create("Тепличная 63", "Подъезд 1", "08:13:CD:00:00:01", "10.0.0.1")
        second = self._create("Тепличная 63", "Подъезд 2", "08:13:CD:00:00:02", "10.0.0.2")
        third = self._create("Горького 45", "Главный вход", "08:13:CD:00:00:03")

        panel_repository.update_panel_api_status(
            first["id"],
            {
                "status": "online",
                "response_time_ms": 42,
                "device_model": "ISCom X1",
                "firmware_version": "2.5.0.14.7",
                "temperature": 56.5,
                "supply_voltage": 12.21,
                "uptime_seconds": 90061,
                "sip_registered": True,
                "reported_mac": first["mac"],
                "last_error": "",
            },
        )
        panel_repository.update_panel_api_status(
            second["id"],
            {"status": "offline", "last_error": "Нет соединения"},
        )
        panel_repository.set_panel_enabled(third["id"], False)

        page = panel_repository.get_panel_page(
            query="10.0.0.1",
            status="online",
            address="Тепличная 63",
            page=1,
            page_size=20,
        )
        self.assertEqual(page["total"], 1)
        self.assertEqual(page["items"][0]["id"], first["id"])
        self.assertEqual(page["items"][0]["uptime_text"], "1 дн. 01:01")
        self.assertEqual(page["items"][0]["supply_voltage"], 12.21)
        self.assertTrue(page["items"][0]["mac_matches"])

        statistics = panel_repository.get_panel_statistics()
        self.assertEqual(statistics["total"], 3)
        self.assertEqual(statistics["online"], 1)
        self.assertEqual(statistics["offline"], 1)
        self.assertEqual(statistics["disabled"], 1)

    def test_status_cache_keeps_last_successful_device_data_on_failure(self):
        item = self._create("Лесная 12", "1", "08:13:CD:00:00:04", "10.0.0.4")
        panel_repository.update_panel_api_status(
            item["id"],
            {
                "status": "online",
                "device_model": "ISCom X1",
                "firmware_version": "2.5.0",
                "last_error": "",
            },
        )
        panel_repository.update_panel_api_status(
            item["id"],
            {"status": "offline", "last_error": "Тайм-аут"},
        )

        cached = panel_repository.get_panel_by_id(item["id"])
        self.assertEqual(cached["network_status"], "offline")
        self.assertEqual(cached["device_model"], "ISCom X1")
        self.assertEqual(cached["firmware_version"], "2.5.0")
        self.assertEqual(cached["last_error"], "Тайм-аут")


class PanelApiTests(unittest.TestCase):
    def setUp(self):
        self.panel = {"ip": "10.10.1.15"}

    @staticmethod
    def _response(*, status=200, payload=None, content=None, content_type="application/json"):
        response = Mock()
        response.status_code = status
        if content is None:
            content = b"{}" if payload is not None else b""
        response.content = content
        response.headers = {"Content-Type": content_type}
        response.json.return_value = payload if payload is not None else {}
        return response

    def test_check_uses_common_basic_auth_and_collects_real_fields(self):
        responses = [
            self._response(
                payload={
                    "model": "GK7205V300",
                    "temperature": 56.5,
                    "mac": "08:13:CD:00:00:01",
                    "deviceModel": "ISCom X1 (rev.5)",
                    "uptime": 1001,
                    "registerStatus": True,
                }
            ),
            self._response(payload={"power": {"dc": 12.21}, "chipId": 1000000000000000001}),
            self._response(payload={"opt": {"name": "2.5.0.14.7"}}),
        ]
        with (
            patch.object(panel_api.settings, "panel_api_login", "common-user"),
            patch.object(panel_api.settings, "panel_api_password", "common-password"),
            patch.object(panel_api.settings, "panel_api_timeout", 2.5),
            patch("app.services.panel_api._http_request", side_effect=responses) as request_mock,
        ):
            result = panel_api.check_panel(self.panel)

        self.assertEqual(result["status"], "online")
        self.assertEqual(result["device_model"], "ISCom X1 (rev.5)")
        self.assertEqual(result["firmware_version"], "2.5.0.14.7")
        self.assertEqual(result["temperature"], 56.5)
        self.assertEqual(result["supply_voltage"], 12.21)
        self.assertTrue(result["sip_registered"])
        self.assertEqual(request_mock.call_count, 3)
        first_call = request_mock.call_args_list[0]
        self.assertEqual(first_call.args[:2], ("GET", "http://10.10.1.15/system/info"))
        self.assertEqual(first_call.kwargs["auth"].username, "common-user")
        self.assertEqual(first_call.kwargs["auth"].password, "common-password")
        self.assertEqual(first_call.kwargs["timeout"], 2.5)
        self.assertEqual(
            request_mock.call_args_list[1].args[:2],
            ("GET", "http://10.10.1.15/v1/mcu/info"),
        )

    def test_check_maps_timeout_and_bad_credentials_to_clear_statuses(self):
        with (
            patch.object(panel_api.settings, "panel_api_login", "user"),
            patch.object(panel_api.settings, "panel_api_password", "password"),
            patch("app.services.panel_api._http_request", side_effect=requests.Timeout()),
        ):
            timeout_result = panel_api.check_panel(self.panel)
        self.assertEqual(timeout_result["status"], "offline")

        with (
            patch.object(panel_api.settings, "panel_api_login", "user"),
            patch.object(panel_api.settings, "panel_api_password", "password"),
            patch(
                "app.services.panel_api._http_request",
                return_value=self._response(status=401),
            ),
        ):
            auth_result = panel_api.check_panel(self.panel)
        self.assertEqual(auth_result["status"], "auth_error")

    def test_snapshot_and_reboot_use_documented_endpoints(self):
        snapshot = self._response(
            content=b"jpeg-data",
            content_type="image/jpeg",
        )
        reboot = self._response(content=b"", content_type="text/plain")
        with (
            patch.object(panel_api.settings, "panel_api_login", "user"),
            patch.object(panel_api.settings, "panel_api_password", "password"),
            patch(
                "app.services.panel_api._http_request",
                side_effect=[snapshot, reboot],
            ) as request_mock,
        ):
            content, content_type = panel_api.get_panel_snapshot(self.panel)
            panel_api.reboot_panel(self.panel)

        self.assertEqual(content, b"jpeg-data")
        self.assertEqual(content_type, "image/jpeg")
        self.assertEqual(request_mock.call_args_list[0].args[:2], ("GET", "http://10.10.1.15/camera/snapshot"))
        self.assertEqual(request_mock.call_args_list[1].args[:2], ("PUT", "http://10.10.1.15/system/reboot"))


if __name__ == "__main__":
    unittest.main()
