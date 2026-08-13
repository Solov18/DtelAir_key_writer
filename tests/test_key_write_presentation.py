import importlib.util
import sys
import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader


_MODEL_SPEC = importlib.util.spec_from_file_location(
    "key_write_models_presentation",
    Path("app/services/key_write_models.py"),
)
_MODELS = importlib.util.module_from_spec(_MODEL_SPEC)
sys.modules[_MODEL_SPEC.name] = _MODELS
_MODEL_SPEC.loader.exec_module(_MODELS)
KeyWriteContext = _MODELS.KeyWriteContext
KeyWriteResult = _MODELS.KeyWriteResult
KeyWriteUiStatus = _MODELS.KeyWriteUiStatus


class KeyWritePresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.environment = Environment(
            loader=FileSystemLoader(Path("app/templates")),
            autoescape=True,
        )
        cls.module = cls.environment.get_template("macros/key_write_ui.html").module

    def status(self, value):
        return str(self.module.status_badge(value))

    def result(self, rows):
        return KeyWriteResult.from_writer(1, rows)

    def test_01_ready(self):
        self.assertIn("Свободен — готов к записи", self.status(KeyWriteUiStatus.READY))

    def test_02_occupied(self):
        context = KeyWriteContext.from_legacy({
            "key_id": 1,
            "key_type_name": "Оранжевый",
            "key_number": "003049",
            "hex_value": "A1B2C3D4",
            "is_used": True,
            "assignments": [{
                "assignment_type_name": "Жилец",
                "owner_name": "Иванов Иван",
                "assignment_address": "ул. Тестовая 1",
                "assignment_apartment": "7",
            }],
            "panels": [{"address": "ул. Тестовая 1", "entrance": "подъезд 1"}],
        })
        html = str(self.module.occupied_context(context))
        for value in ("Ключ уже используется", "Текущее назначение", "Иванов Иван", "кв. 7", "подъезд 1"):
            self.assertIn(value, html)
        for duplicate in ("Оранжевый", "003049", "A1B2C3D4"):
            self.assertNotIn(duplicate, html)

    def test_03_action_required(self):
        self.assertIn("Требуется действие", self.status(KeyWriteUiStatus.ACTION_REQUIRED))

    def test_04_already_all(self):
        self.assertIn("Уже записан на всех выбранных панелях", self.status(KeyWriteUiStatus.ALREADY_ALL))

    def test_05_success(self):
        result = self.result([{"panel": {"id": 1}, "status": "SUCCESS", "ok": True, "written": True}])
        self.assertIn("Успешно", str(self.module.result_summary(result)))

    def test_06_partial(self):
        result = self.result([
            {"panel": {"id": 1}, "status": "SUCCESS", "ok": True, "written": True},
            {"panel": {"id": 2}, "status": "ERROR", "ok": False},
        ])
        self.assertIn("Выполнено частично", str(self.module.result_summary(result)))

    def test_07_failed(self):
        result = self.result([{"panel": {"id": 1}, "status": "ERROR", "ok": False}])
        self.assertIn("Ошибка", str(self.module.result_summary(result)))

    def test_08_timeout(self):
        result = self.result([{"panel": {"id": 1}, "status": "TIMEOUT", "ok": False, "message": "SECRET TRACE"}])
        html = str(self.module.panel_result(result.panel_results[0]))
        self.assertIn("Панель не ответила вовремя", html)
        self.assertNotIn("SECRET TRACE", html)

    def test_09_auth_error(self):
        result = self.result([{"panel": {"id": 1}, "status": "AUTH_ERROR", "ok": False}])
        self.assertIn("Ошибка авторизации на панели", str(self.module.panel_result(result.panel_results[0])))

    def test_10_one_success_and_one_failed(self):
        result = self.result([
            {"panel": {"id": 1}, "status": "SUCCESS", "ok": True, "written": True},
            {"panel": {"id": 2}, "status": "CONNECTION_ERROR", "ok": False},
        ])
        summary = str(self.module.result_summary(result))
        panels = "".join(str(self.module.panel_result(item)) for item in result.panel_results)
        self.assertIn("Выполнено частично", summary)
        self.assertIn("Успешно записан", panels)
        self.assertIn("Нет соединения с панелью", panels)

    def test_11_already_present(self):
        result = self.result([{"panel": {"id": 1}, "status": "ALREADY_EXISTS", "ok": True}])
        html = str(self.module.panel_result(result.panel_results[0]))
        self.assertIn("Уже записан", html)
        self.assertIn("key-write-status--already_all", html)

    def test_12_reassign_selected(self):
        html = str(self.module.action_selector(form_id="writeForm", selected_action="reassign"))
        self.assertIn('value="reassign" checked', html)
        self.assertIn('value="add_panels"', html)
        self.assertIn('form="writeForm"', html)

    def test_13_add_panels_selected(self):
        html = str(self.module.action_selector(selected_action="add_panels"))
        self.assertIn('value="add_panels" checked', html)
        self.assertIn("Только добавить на выбранные панели", html)


if __name__ == "__main__":
    unittest.main()
