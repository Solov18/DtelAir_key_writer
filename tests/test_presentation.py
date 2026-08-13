import unittest
from pathlib import Path

from app.presentation import operation_status_name, operation_status_tone
from app.repositories.log_repository import ACTION_NAMES, normalize_operation_row
from app.templates_config import format_datetime, format_datetime_seconds, templates


class PresentationTests(unittest.TestCase):
    def test_key_assignment_uses_compact_smart_address_search(self):
        template = Path("app/templates/key_detail.html").read_text(encoding="utf-8")
        styles = Path("app/static/css/pages/keys_log.css").read_text(encoding="utf-8")

        self.assertNotIn('list="assignment-addresses"', template)
        self.assertNotIn('<datalist id="assignment-addresses">', template)
        self.assertIn('data-smart-search="panels"', template)
        self.assertIn('data-smart-submit="false"', template)
        self.assertIn('class="key-assignment-owner-type"', template)
        self.assertIn('class="key-assignment-apartment"', template)
        self.assertIn(".key-assignment-address-control", styles)

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
        self.assertIn(".uk-row-actions :is(.uk-open-card-link, .uk-edit-card-link)", theme_css)
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

    def test_shared_datetime_formatters_cover_supported_values(self):
        from datetime import datetime, timezone

        from app.templates_config import format_datetime, format_datetime_seconds

        aware = datetime(2026, 8, 3, 20, 42, 8, 214655, tzinfo=timezone.utc)
        self.assertEqual(format_datetime(aware), "03.08.2026 20:42")
        self.assertEqual(format_datetime_seconds(aware), "03.08.2026 20:42:08")
        self.assertEqual(format_datetime("2026-08-03T20:42:08.214655+03:00"), "03.08.2026 20:42")
        self.assertEqual(format_datetime_seconds("2026-08-03T20:42:08.214655+03:00"), "03.08.2026 20:42:08")
        self.assertEqual(format_datetime(None), "—")
        self.assertEqual(format_datetime(""), "—")

    def test_dynamic_datetime_formatter_is_loaded_globally(self):
        script = Path("app/static/js/date-time.js").read_text(encoding="utf-8")
        base = Path("app/templates/base.html").read_text(encoding="utf-8")

        self.assertIn("window.formatDateTime = formatDateTime", script)
        self.assertIn('value instanceof Date', script)
        self.assertIn('options.withSeconds', script)
        self.assertIn('/static/js/date-time.js?v=1', base)

    def test_selected_key_sidebar_wraps_values_and_supports_copying(self):
        template = Path("app/templates/keys.html").read_text(encoding="utf-8")
        styles = Path("app/static/css/pages/keys_log.css").read_text(encoding="utf-8")
        copy_script = Path("app/static/js/copy-button.js").read_text(encoding="utf-8")
        base = Path("app/templates/base.html").read_text(encoding="utf-8")

        self.assertIn("keys-copy-button", template)
        self.assertIn("data-copy-value", template)
        self.assertIn("copyValue(button)", copy_script)
        self.assertIn("event.stopPropagation()", copy_script)
        self.assertIn('/static/js/copy-button.js?v=1', base)
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
        self.assertIn('show({overlay: method !== "GET"})', script)
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
        self.assertIn('./modal.css?v=2', style)
        self.assertIn('./detail-sidebar.css?v=1', style)
        self.assertIn('event.key === "Tab"', modal_script)
        self.assertIn('window.AppModal = {open, close, markClean}', modal_script)
        self.assertIn('queryTokens.every', combobox)
        self.assertGreaterEqual(uk_detail.count('data-combobox-search="true"'), 1)
        self.assertIn('data-search="{{ panel.address }}', uk_detail)
        self.assertIn('data-uk-key-selection', uk_detail)
        self.assertIn('data-smart-search-url="/api/keys/search"', uk_detail)
        self.assertIn('data-smart-search-params="#ukIssueKeyType:key_type_id"', uk_detail)
        self.assertIn('Все типы', uk_detail)
        self.assertIn('html *::-webkit-scrollbar-thumb', scroll)

    def test_low_risk_presentation_foundations_are_shared(self):
        components = Path("app/static/css/components.css").read_text(encoding="utf-8")
        modal_styles = Path("app/static/css/modal.css").read_text(encoding="utf-8")
        modal_macro = Path("app/templates/macros/modal.html").read_text(encoding="utf-8")
        employees = Path("app/templates/employees.html").read_text(encoding="utf-8")
        modal_script = Path("app/static/js/modal.js").read_text(encoding="utf-8")

        for class_name in (
            ".btn-primary",
            ".btn-secondary",
            ".btn-danger",
            ".btn-success",
            ".btn-icon",
            ".btn-sm",
            ".entity-card",
        ):
            self.assertIn(class_name, components)

        self.assertIn(".modal-shell__header", modal_styles)
        self.assertIn("macro modal_shell", modal_macro)
        self.assertEqual(employees.count("call modal_shell("), 2)
        self.assertIn("employee-summary-card entity-card entity-card--compact", employees)
        self.assertIn("btn btn-secondary employee-archive-link", employees)
        self.assertIn("data-close-employee-modal", modal_macro)
        self.assertIn('title: "Закрыть без сохранения?"', modal_script)

    def test_message_preview_exposes_used_key_choices_and_panel_states(self):
        template = Path("app/templates/message_preview.html").read_text(
            encoding="utf-8"
        )
        key_write_ui = Path("app/templates/macros/key_write_ui.html").read_text(
            encoding="utf-8"
        )
        script = Path("app/static/js/message.js").read_text(encoding="utf-8")
        picker_script = Path("app/static/js/panel-picker.js").read_text(
            encoding="utf-8"
        )
        styles = Path("app/static/css/pages/message.css").read_text(
            encoding="utf-8"
        )

        self.assertIn("occupied_context", template)
        self.assertIn("Ключ уже используется", key_write_ui)
        self.assertIn("Переназначить ключ", key_write_ui)
        self.assertIn("Только добавить на выбранные панели", key_write_ui)
        self.assertIn("field_name='occupied_action'", key_write_ui)
        self.assertIn('value="reassign"', key_write_ui)
        self.assertIn('value="add_panels"', key_write_ui)
        self.assertIn("data-known-panels", template)
        self.assertIn("'partial': 'Выполнено частично'", key_write_ui)
        self.assertIn("Уже записан на всех выбранных панелях", script)
        self.assertIn("Его текущее назначение в CRM будет заменено новым", script)
        self.assertIn("без изменения текущего назначения", script)
        shared_styles = Path("app/static/css/components.css").read_text(encoding="utf-8")
        self.assertIn(".key-write-actions", shared_styles)
        self.assertIn("body.light-theme", styles)
        self.assertIn("+ Добавить дополнительные панели", template)
        self.assertIn('id="messagePanelPicker"', template)
        self.assertIn('data-panel-source="automatic"', template)
        self.assertIn('id="manualPanelSection"', template)
        self.assertIn('id="messageManualPanelList"', template)
        self.assertIn('id="messagePanelPickerSelection"', template)
        self.assertIn('id="messagePanelPickerChips"', template)
        self.assertIn("Добавлена вручную", script)
        self.assertIn("Панель уже выбрана", picker_script)
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
        key_write_ui = Path("app/templates/macros/key_write_ui.html").read_text(
            encoding="utf-8"
        )
        script = Path("app/static/js/manual-write.js").read_text(encoding="utf-8")
        picker_script = Path("app/static/js/panel-picker.js").read_text(
            encoding="utf-8"
        )
        smart_search = Path("app/static/js/smart-search.js").read_text(encoding="utf-8")
        styles = Path("app/static/css/pages/manual_write.css").read_text(encoding="utf-8")

        self.assertIn('id="open-manual-panel-picker"', template)
        self.assertIn('id="manualPanelPicker"', template)
        self.assertIn('id="manualPanelList"', template)
        self.assertIn('id="automaticPanelCount"', template)
        self.assertIn('id="manualPanelCount"', template)
        self.assertIn("Основной адрес", template)
        self.assertIn("SmartAutocomplete.enhance", picker_script)
        self.assertIn("globalLoader: false", smart_search)
        self.assertIn('event.key === "Enter"', smart_search)
        self.assertIn("automatic_panel_ids", script)
        self.assertIn("manual_panel_ids", script)
        self.assertIn("panelAlreadySelected", script)
        self.assertIn("occupied_context", template)
        self.assertIn('data-occupied-key', key_write_ui)
        self.assertIn('value="reassign"', key_write_ui)
        self.assertIn('value="add_panels"', key_write_ui)
        self.assertIn("showDangerConfirm", script)
        self.assertIn("showConfirm", script)
        shared_styles = Path("app/static/css/components.css").read_text(encoding="utf-8")
        self.assertIn(".key-write-actions", shared_styles)
        self.assertIn("manual-panel-option--manual", styles)
        self.assertIn(".manual-panel-actions", styles)
        actions = styles.split(".manual-panel-actions {", 1)[1].split("}", 1)[0]
        self.assertIn("gap:10px", actions)
        self.assertNotIn("position:absolute", actions)

    def test_shared_panel_picker_owns_search_lifecycle_and_selection(self):
        base = Path("app/templates/base.html").read_text(encoding="utf-8")
        picker = Path("app/static/js/panel-picker.js").read_text(encoding="utf-8")
        smart_search = Path("app/static/js/smart-search.js").read_text(encoding="utf-8")
        message = Path("app/static/js/message.js").read_text(encoding="utf-8")
        manual = Path("app/static/js/manual-write.js").read_text(encoding="utf-8")

        self.assertIn('/static/js/panel-picker.js?v=1', base)
        self.assertIn("class PanelPicker", picker)
        self.assertIn("SmartAutocomplete.enhance", picker)
        self.assertIn('queryParameter: "query"', picker)
        self.assertIn("renderMenu: false", picker)
        self.assertIn("onFinally: () => this.setLoading(false)", picker)
        self.assertIn("new AbortController()", smart_search)
        self.assertIn('state.request?.abort("replaced")', smart_search)
        self.assertIn("finally", smart_search)
        self.assertIn("globalLoader: false", smart_search)
        self.assertIn('event.key === "Enter"', smart_search)
        self.assertIn('event.key === "Escape"', picker)
        self.assertIn("isAlreadySelected", picker)
        self.assertIn("addSelected()", picker)
        self.assertIn("removeManual(event)", picker)
        self.assertIn("emptyText", picker)
        self.assertIn("new window.PanelPicker", message)
        self.assertIn("new window.PanelPicker", manual)
        self.assertIn('endpoint: "/message/panels/search"', message)
        self.assertIn('endpoint: "/message/panels/search"', manual)
        self.assertNotIn("new AbortController()", message)
        self.assertNotIn("new AbortController()", manual)
        self.assertNotIn("async function searchPanels", message)
        self.assertNotIn("async function searchPanels", manual)

    def test_remote_smart_search_contract_is_centralized(self):
        smart_search = Path("app/static/js/smart-search.js").read_text(encoding="utf-8")
        picker = Path("app/static/js/panel-picker.js").read_text(encoding="utf-8")
        uk_detail = Path("app/static/js/uk-detail.js").read_text(encoding="utf-8")

        for fragment in (
            "debounceMs",
            "window.setTimeout(execute",
            'state.request?.abort("replaced")',
            'abortReason = "timeout"',
            "if (!response.ok)",
            "await response.json()",
            'error.smartSearchReason = abortReason || "aborted"',
            'event.key === "ArrowDown"',
            'event.key === "ArrowUp"',
            'event.key === "Enter"',
            'event.key === "Escape"',
            'addEventListener("pointerdown"',
            "state.options.searchButton",
            "minimumQueryLength",
            "state.options.renderer",
            "state.options.getParams",
            "state.options.onSelect",
            "state.options.onLoading",
            "state.options.onLoaded",
            "state.options.onError",
            "state.options.onFinally",
            "globalLoader: false",
            "function renderState",
            '"smart-search-loading"',
            '"smart-search-error"',
            "const selected = !state.menu.hidden",
        ):
            self.assertIn(fragment, smart_search)

        self.assertIn('empty.textContent = state.options.emptyText || "Ничего не найдено"', smart_search)
        self.assertIn("SmartAutocomplete.enhance", picker)
        self.assertIn("SmartAutocomplete.enhance", uk_detail)
        self.assertIn("minimumQueryLength: 0", uk_detail)
        self.assertNotIn("fetchSearchJson", uk_detail)
        self.assertNotIn("debounceTimer", uk_detail)
        self.assertNotIn("requestSequence", uk_detail)
        self.assertNotIn("new AbortController()", picker)
        self.assertNotIn("new AbortController()", uk_detail)

    def test_ui_followup_uses_clear_multi_panel_labels_and_aligned_controls(self):
        uk_template = Path("app/templates/uk.html").read_text(encoding="utf-8")
        uk_detail = Path("app/templates/uk_detail.html").read_text(encoding="utf-8")
        uk_styles = Path("app/static/css/pages/uk.css").read_text(encoding="utf-8")

        self.assertNotIn("Ключей на нескольких панелях", uk_template)
        self.assertNotIn("На нескольких панелях", uk_template)
        self.assertIn('class="uk-edit-card-link"', uk_template)
        self.assertIn("Ключ на нескольких панелях", uk_detail)
        self.assertNotIn("Ключей-вездеходов", uk_template)
        self.assertIn(".uk-summary-card.is-text-only", uk_styles)
        self.assertIn("#ukIssueModal :is(.uk-picker-search-row > button", uk_styles)
        self.assertIn("height: var(--control-height, 42px)", uk_styles)
        self.assertIn("body.light-theme #ukIssueModal .uk-neon-action", uk_styles)
        self.assertIn("#ukAddModal .uk-modal-card", uk_styles)
        self.assertIn("#ukEditModal .uk-modal-card", uk_styles)
        self.assertIn("width: min(900px, calc(100vw - 24px))", uk_styles)

    def test_key_copy_actions_use_shared_svg_icon_and_status_can_wrap(self):
        key_template = Path("app/templates/keys.html").read_text(encoding="utf-8")
        key_styles = Path("app/static/css/pages/keys_log.css").read_text(encoding="utf-8")
        components = Path("app/static/css/components.css").read_text(encoding="utf-8")

        self.assertGreaterEqual(key_template.count('class="copy-button keys-copy-button"'), 3)
        self.assertGreaterEqual(key_template.count('<rect x="8" y="8" width="11" height="11"'), 3)
        self.assertGreaterEqual(key_template.count('class="copy-button__success-icon"'), 3)
        self.assertNotIn(">⧉</button>", key_template)
        self.assertIn(".keys-copy-button svg", key_styles)
        status_rule = components.split(".key-write-status{", 1)[1].split("}", 1)[0]
        self.assertIn("white-space:normal", status_rule)
        self.assertIn("overflow-wrap:anywhere", status_rule)


if __name__ == "__main__":
    unittest.main()
