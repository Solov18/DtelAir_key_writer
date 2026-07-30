import unittest
from pathlib import Path

from app.presentation import operation_status_name, operation_status_tone
from app.repositories.log_repository import ACTION_NAMES, normalize_operation_row
from app.templates_config import templates


class PresentationTests(unittest.TestCase):
    def test_crm_statuses_are_human_readable(self):
        self.assertEqual(operation_status_name("SUCCESS"), "Успешно")
        self.assertEqual(
            operation_status_name("AUTH_REQUIRED"),
            "Требуется вход в CRM",
        )
        self.assertEqual(operation_status_name("HTTP_503"), "Ошибка CRM (HTTP 503)")
        self.assertEqual(operation_status_tone("AUTH_REQUIRED"), "error")
        self.assertEqual(operation_status_tone("DRY_RUN"), "warning")

    def test_old_message_action_is_translated(self):
        row = normalize_operation_row(
            {
                "action": "resident",
                "status": "SUCCESS",
                "printed_number": "40579",
            }
        )

        self.assertEqual(row["action_name"], "Из сообщения")
        self.assertEqual(row["status_name"], "Успешно")
        self.assertEqual(row["status_tone"], "success")

    def test_panel_monitor_actions_are_translated(self):
        self.assertEqual(ACTION_NAMES["panel_check"], "Проверка панели")
        self.assertEqual(
            ACTION_NAMES["panel_monitor_request"],
            "Запуск мониторинга панелей",
        )

    def test_shared_combobox_and_selected_row_components_are_used(self):
        script = Path("app/static/js/combobox.js").read_text(encoding="utf-8")
        components = Path("app/static/css/components.css").read_text(encoding="utf-8")
        layouts = Path("app/static/css/filter-layouts.css").read_text(encoding="utf-8")
        base_css = Path("app/static/css/base.css").read_text(encoding="utf-8")
        theme_css = Path("app/static/css/theme-system.css").read_text(encoding="utf-8")
        theme_script = Path("app/static/js/theme.js").read_text(encoding="utf-8")
        base = Path("app/templates/base.html").read_text(encoding="utf-8")

        self.assertIn('select:not([data-native-select])', script)
        self.assertIn("MutationObserver", script)
        self.assertIn("document.body.appendChild(popup)", script)
        self.assertIn("containsTarget", script)
        self.assertIn("const instances = new WeakMap()", script)
        self.assertIn("/static/js/combobox.js", base)
        self.assertIn(".app-combobox__popup", components)
        self.assertIn(".filter-bar", layouts)
        self.assertIn(".filter-bar .filter-bar__search > input", layouts)
        self.assertIn("var(--search-text-offset)", layouts)
        self.assertNotIn(".filter-bar input:not([type=\"checkbox\"])", components)
        self.assertIn("--control-height: 44px", base_css)
        self.assertIn("--surface-page:", theme_css)
        self.assertIn("--color-placeholder:", theme_css)
        self.assertIn("--surface-row-selected:", theme_css)
        self.assertIn(".app-combobox__popup", theme_css)
        self.assertIn(".app-dialog__panel", theme_css)
        self.assertIn("app:themechange", theme_script)
        self.assertIn("document.documentElement.style.colorScheme", theme_script)
        self.assertLess(
            base.index("/static/css/filter-layouts.css"),
            base.index("/static/css/theme-system.css"),
        )
        self.assertIn(".log-filter-row--primary", layouts)
        self.assertIn("@media (max-width: 900px)", layouts)
        self.assertIn(".data-row--selected", components)
        self.assertNotIn("body.light-theme button,\n", Path("app/static/css/light-theme.css").read_text(encoding="utf-8"))
        self.assertIn("--scroll-size: 8px", base_css)
        self.assertIn("--font-table: 13px", base_css)
        self.assertIn(".employee-row-actions button", theme_css)
        self.assertIn(".uk-row-actions .uk-open-card-link", theme_css)
        self.assertIn(".log-period-button.is-active", theme_css)
        self.assertIn(".uk-history-scroll td", theme_css)
        self.assertIn(".smart-search-option.is-active", Path("app/static/css/smart-search.css").read_text(encoding="utf-8"))
        self.assertIn("scrollbar-color: var(--scroll-thumb) var(--scroll-track)", Path("app/static/css/scroll.css").read_text(encoding="utf-8"))

        for name in (
            "keys.html",
            "keys_missing.html",
            "employees.html",
            "panels.html",
            "uk.html",
            "log.html",
            "search.html",
        ):
            source = Path("app/templates", name).read_text(encoding="utf-8")
            self.assertIn("filter-bar", source)

        for name in ("keys.html", "employees.html", "panels.html", "uk.html"):
            source = Path("app/templates", name).read_text(encoding="utf-8")
            self.assertIn("data-row--selected", source)

    def test_all_templates_compile_after_combobox_enhancement(self):
        for name in templates.env.list_templates():
            if name.endswith(".html"):
                templates.env.get_template(name)


if __name__ == "__main__":
    unittest.main()
