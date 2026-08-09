import unittest
from pathlib import Path

from app.presentation import operation_status_name, operation_status_tone
from app.repositories.log_repository import ACTION_NAMES, normalize_operation_row
from app.templates_config import format_datetime, format_datetime_seconds, templates


class PresentationTests(unittest.TestCase):
    def test_shared_datetime_formatter_hides_timezone_and_microseconds(self):
        value = "2026-08-03 20:42:08.214655+03:00"
        self.assertEqual(format_datetime(value), "03.08.2026 20:42")
        self.assertEqual(format_datetime_seconds(value), "03.08.2026 20:42:08")
        self.assertEqual(format_datetime(None), "—")

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

    def test_key_write_audit_payload_is_presented_without_raw_json(self):
        row = normalize_operation_row(
            {
                "action": "key_write_decision",
                "status": "SUCCESS",
                "details": (
                    '{"write_option":"write_free_key",'
                    '"selected_panel_ids":[383,382],'
                    '"new_panel_ids":[383,382],'
                    '"successful_panel_ids":[383,382],'
                    '"failed_panel_ids":[], '
                    '"new_assignment":{"type":"resident",'
                    '"address":"пер. Богдана Хмельницкого 10",'
                    '"apartment":"23"}}'
                ),
            }
        )

        self.assertEqual(row["action_name"], "Итог записи ключа")
        self.assertIn("Обработано панелей: 2 из 2", row["details_view"])
        self.assertIn("пер. Богдана Хмельницкого 10, кв. 23", row["details_view"])
        self.assertNotIn("write_option", row["details_view"])

        panel_row = normalize_operation_row(
            {
                "action": "write_free_key",
                "status": "SUCCESS",
                "details": (
                    '{"target_address":"пер. Богдана Хмельницкого 10",'
                    '"target_apartment":"23",'
                    '"panel_name":"основной вход"}'
                ),
            }
        )
        self.assertEqual(panel_row["action_name"], "Запись свободного ключа")
        self.assertEqual(
            panel_row["details_view"],
            "Ключ записан на панель «основной вход»; адрес: пер. Богдана Хмельницкого 10; кв. 23.",
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

    def test_selected_key_sidebar_wraps_values_and_supports_copying(self):
        template = Path("app/templates/keys.html").read_text(encoding="utf-8")
        styles = Path("app/static/css/pages/keys_log.css").read_text(encoding="utf-8")

        self.assertIn("keys-copy-button", template)
        self.assertIn("data-copy-value", template)
        self.assertIn("copyKeySidebarValue", template)
        self.assertIn("keys-current-assignment-value", template)
        self.assertIn("var(--detail-sidebar-width, 390px)", styles)
        self.assertIn("detail-layout", template)
        self.assertIn("detail-sidebar", template)
        self.assertIn("user-select: text", styles)
        self.assertIn("overflow-wrap: anywhere", styles)

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
        modal_script = Path("app/static/js/modal.js").read_text(encoding="utf-8")

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

        self.assertIn("event.target === modal", modal_script)
        self.assertIn('event.key === "Escape"', modal_script)
        self.assertIn("event.stopImmediatePropagation()", modal_script)
        self.assertNotIn('document.querySelectorAll(".modal-backdrop")', source)

    def test_shared_modal_scroll_detail_and_large_list_search_components(self):
        base = Path("app/templates/base.html").read_text(encoding="utf-8")
        modal_script = Path("app/static/js/modal.js").read_text(encoding="utf-8")
        combobox = Path("app/static/js/combobox.js").read_text(encoding="utf-8")
        uk_detail = Path("app/templates/uk_detail.html").read_text(encoding="utf-8")
        style = Path("app/static/css/style.css").read_text(encoding="utf-8")
        scroll = Path("app/static/css/scroll.css").read_text(encoding="utf-8")

        self.assertIn('/static/js/modal.js?v=1', base)
        self.assertIn('./modal.css?v=1', style)
        self.assertIn('./detail-sidebar.css?v=1', style)
        self.assertIn('event.key === "Tab"', modal_script)
        self.assertIn('window.AppModal = {open, close, markClean}', modal_script)
        self.assertIn('queryTokens.every', combobox)
        self.assertGreaterEqual(uk_detail.count('data-combobox-search="true"'), 1)
        self.assertIn('data-search="{{ panel.address }}', uk_detail)
        self.assertIn('data-uk-key-picker', uk_detail)
        self.assertIn('data-uk-key-type', uk_detail)
        self.assertIn('Все типы', uk_detail)
        self.assertIn('html *::-webkit-scrollbar-thumb', scroll)

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
        self.assertIn("+ Добавить дополнительные панели", template)
        self.assertIn('id="messagePanelPicker"', template)
        self.assertIn('data-panel-source="automatic"', template)
        self.assertIn('id="manualPanelSection"', template)
        self.assertIn('id="messageManualPanelList"', template)
        self.assertIn('id="messagePanelPickerSelection"', template)
        self.assertIn('id="messagePanelPickerChips"', template)
        self.assertIn("Добавлена вручную", script)
        self.assertIn("Панель уже выбрана", script)
        self.assertIn("grid-template-columns: repeat(2", styles)
        self.assertIn("grid-template-columns: repeat(3", styles)
        self.assertIn('name = checkbox.dataset.panelSource === "manual"', script)
        self.assertIn("automatic_panel_ids", script)
        self.assertIn("manual_panel_ids", script)
        self.assertIn(".message-panel-picker", styles)
        self.assertIn("panelsEmpty.hidden = checkedPanels.length > 0", script)
        self.assertIn(".message-empty-state[hidden]", styles)
        self.assertIn(".panel-card__actions", styles)
        self.assertIn("gap: 10px", styles)
        self.assertIn(".panel-card__checkbox", styles)
        remove_rule = styles.split(".message-manual-panel-remove {", 1)[1].split("}", 1)[0]
        self.assertNotIn("position: absolute", remove_rule)
        self.assertNotIn("margin-right: -", remove_rule)


    def test_manual_write_supports_additional_panels_without_changing_assignment(self):
        template = Path("app/templates/manual_write.html").read_text(encoding="utf-8")
        script = Path("app/static/js/manual-write.js").read_text(encoding="utf-8")
        styles = Path("app/static/css/pages/manual_write.css").read_text(encoding="utf-8")

        self.assertIn('id="open-manual-panel-picker"', template)
        self.assertIn('id="manualPanelPicker"', template)
        self.assertIn('id="manualPanelList"', template)
        self.assertIn('id="automaticPanelCount"', template)
        self.assertIn('id="manualPanelCount"', template)
        self.assertIn("Основной адрес", template)
        self.assertIn("globalLoader: false", script)
        self.assertIn('event.key === "Enter"', script)
        self.assertIn("automatic_panel_ids", script)
        self.assertIn("manual_panel_ids", script)
        self.assertIn("panelAlreadySelected", script)
        self.assertIn("manual-panel-option--manual", styles)
        self.assertIn(".manual-panel-actions", styles)
        actions = styles.split(".manual-panel-actions {", 1)[1].split("}", 1)[0]
        self.assertIn("gap:10px", actions)
        self.assertNotIn("position:absolute", actions)


if __name__ == "__main__":
    unittest.main()
