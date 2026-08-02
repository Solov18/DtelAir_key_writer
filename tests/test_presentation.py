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

    def test_topbar_uses_shared_compact_navigation_layout(self):
        base = Path("app/templates/base.html").read_text(encoding="utf-8")
        layout = Path("app/static/css/layout.css").read_text(encoding="utf-8")
        components = Path("app/static/css/components.css").read_text(encoding="utf-8")
        theme = Path("app/static/css/theme-system.css").read_text(encoding="utf-8")

        self.assertIn('{% block page_name %}', base)
        self.assertIn('class="topbar-section-divider"', base)
        self.assertIn('class="top-info topbar-item"', base)
        self.assertIn('class="user-pill topbar-item"', base)
        self.assertIn('class="theme-toggle topbar-item"', base)
        self.assertIn('class="topbar-logout topbar-item"', base)
        self.assertNotIn('class="training-toggle', base)
        self.assertNotIn("role_label(", base)
        self.assertIn("height: 72px", layout)
        self.assertIn("@media (max-width: 900px)", layout)
        self.assertIn(".theme-text,", layout)
        self.assertIn("min-height: 44px", components)
        self.assertIn("--topbar-item-background:", theme)

    def test_global_loader_is_shared_and_covers_async_requests_safely(self):
        base = Path("app/templates/base.html").read_text(encoding="utf-8")
        login = Path("app/templates/login.html").read_text(encoding="utf-8")
        loader_template = Path("app/templates/_global_loader.html").read_text(encoding="utf-8")
        styles = Path("app/static/css/global-loader.css").read_text(encoding="utf-8")
        script = Path("app/static/js/global-loader.js").read_text(encoding="utf-8")

        self.assertEqual(loader_template.count('id="globalLoader"'), 1)
        self.assertIn("{% include '_global_loader.html' %}", base)
        self.assertIn("{% include '_global_loader.html' %}", login)
        self.assertIn("/static/js/global-loader.js", base)
        self.assertIn("/static/js/global-loader.js", login)
        self.assertIn('@import url("./global-loader.css', Path("app/static/css/style.css").read_text(encoding="utf-8"))
        self.assertLess(
            base.index("const nativeFetch = window.fetch.bind(window)"),
            base.index("/static/js/global-loader.js"),
        )
        self.assertIn("const requests = new Map()", script)
        self.assertIn("window.showGlobalLoader = show", script)
        self.assertIn("window.hideGlobalLoader = hide", script)
        self.assertIn("async function runWithLoader", script)
        self.assertIn("finally {\n            hide(requestId);", script)
        self.assertIn('addEventListener("loadend"', script)
        self.assertIn('document.addEventListener("submit"', script)
        self.assertIn("HTMLFormElement.prototype.submit", script)
        self.assertIn('document.addEventListener("click"', script)
        self.assertIn('options.globalLoader === false', script)
        self.assertIn("isDownloadLink(anchor)", script)
        self.assertIn("isNestedInteractiveClick(event, navigationTarget)", script)
        self.assertIn('"button",', script)
        self.assertIn("maxDuration: 30000", script)
        self.assertIn("window.submitHtmlFormWithLoader = submitHtmlForm", script)
        self.assertIn("const controller = new AbortController()", script)
        self.assertIn("controller.abort(), 45000", script)
        self.assertIn("window.clearTimeout(requestTimeout)", script)
        self.assertIn("maxDuration: 50000", script)
        self.assertIn("overlayDelay = 260", script)
        self.assertIn("requests.size", script)
        self.assertIn(".global-loader.is-overlay-visible", styles)
        self.assertIn("body.global-loader-blocking", styles)
        self.assertIn("var(--surface-overlay)", styles)
        self.assertIn("var(--color-heading)", styles)
        self.assertIn("global-loader__ring--outer", loader_template)
        self.assertIn("global-loader__ring--middle", loader_template)
        self.assertIn("global-loader__ring--inner", loader_template)
        self.assertIn("global-loader-spin-reverse", styles)
        self.assertIn("global-loader-pulse", styles)
        self.assertIn("Загрузка…", loader_template)
        self.assertNotIn("Выполняется операция…", loader_template)

    def test_key_registry_modals_close_only_with_explicit_cross(self):
        source = Path("app/templates/keys.html").read_text(encoding="utf-8")

        for modal_id in (
            "keyArbitraryModal",
            "keyMissingModal",
            "keyPrepareModal",
            "keyImportModal",
            "keyTypesModal",
        ):
            self.assertIn(
                f'id="{modal_id}" data-dismiss="explicit"',
                source,
            )
            self.assertIn(
                f'data-close="{modal_id}" aria-label="Закрыть">×</button>',
                source,
            )

        self.assertIn(
            "event.target === modal && modal.dataset.dismiss !== \"explicit\"",
            source,
        )
        self.assertIn(
            "document.querySelector('.modal-backdrop[data-dismiss=\"explicit\"].active')",
            source,
        )

    def test_message_preview_exposes_used_key_choices_and_panel_states(self):
        template = Path("app/templates/message_preview.html").read_text(
            encoding="utf-8"
        )
        script = Path("app/static/js/message.js").read_text(encoding="utf-8")
        styles = Path("app/static/css/pages/message.css").read_text(
            encoding="utf-8"
        )

        self.assertIn("Ключ уже используется", template)
        self.assertIn("Переназначить на новый адрес", template)
        self.assertIn("Добавить ещё на выбранные панели", template)
        self.assertIn('name="occupied_action" value="reassign"', template)
        self.assertIn('name="occupied_action" value="add_panels"', template)
        self.assertIn("data-known-panels", template)
        self.assertIn("Частично записан на выбранных панелях", template)
        self.assertIn("Уже записан на всех выбранных панелях", script)
        self.assertIn("Его текущее назначение в CRM будет заменено новым", script)
        self.assertIn("без изменения текущего назначения", script)
        self.assertIn(".message-write-choice", styles)
        self.assertIn("body.light-theme", styles)


if __name__ == "__main__":
    unittest.main()
