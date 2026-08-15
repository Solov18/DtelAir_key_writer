import asyncio
import io
import time
import unittest
from unittest.mock import patch

from fastapi import Request, UploadFile

from app.routers.keys import keys_import
from app.routers.panels import panels_import
from app.main import app


def _request(path: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [],
            "session": {"user": {"full_name": "Тест"}},
        }
    )


class ImportRouteResponsivenessTests(unittest.IsolatedAsyncioTestCase):
    def test_import_endpoints_are_registered_for_post(self):
        registered = {
            (route.path, method)
            for route in app.routes
            for method in (getattr(route, "methods", None) or set())
        }
        self.assertIn(("/keys/import", "POST"), registered)
        self.assertIn(("/panels/import", "POST"), registered)
        self.assertNotIn(("/keys", "POST"), registered)

    async def _assert_route_does_not_block_event_loop(
        self,
        route,
        importer_path: str,
        path: str,
        report: dict,
    ) -> None:
        import_started = asyncio.Event()

        def slow_import(*_args):
            import_started_loop.call_soon_threadsafe(import_started.set)
            time.sleep(0.12)
            return report

        import_started_loop = asyncio.get_running_loop()
        upload = UploadFile(file=io.BytesIO(b"test"), filename="import.xlsx")

        with patch(importer_path, side_effect=slow_import), patch(
            f"{route.__module__}.log_event"
        ):
            task = asyncio.create_task(route(_request(path), upload))
            await asyncio.wait_for(import_started.wait(), timeout=0.5)
            await asyncio.sleep(0.02)
            self.assertFalse(task.done())
            response = await asyncio.wait_for(task, timeout=1)

        self.assertEqual(response.status_code, 303)

    async def test_key_import_keeps_event_loop_responsive(self):
        await self._assert_route_does_not_block_event_loop(
            keys_import,
            "app.routers.keys.import_keys_file",
            "/keys/import",
            {
                "created_types": 0,
                "added": 1,
                "updated": 0,
                "duplicates": 0,
                "errors": 0,
            },
        )

    async def test_panel_import_keeps_event_loop_responsive(self):
        await self._assert_route_does_not_block_event_loop(
            panels_import,
            "app.routers.panels.import_panels_excel",
            "/panels/import",
            {"added": 1, "updated": 0, "skipped": 0, "errors": 0},
        )
