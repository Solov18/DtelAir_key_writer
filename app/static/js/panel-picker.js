(function (global) {
    "use strict";

    const DEFAULT_ENDPOINT = "/message/panels/search";

    function escapeHtml(value) {
        const node = document.createElement("span");
        node.textContent = String(value ?? "");
        return node.innerHTML;
    }

    function decodePanel(checkbox) {
        return JSON.parse(decodeURIComponent(checkbox.dataset.panel || "%7B%7D"));
    }

    class PanelPicker {
        constructor(options) {
            this.options = {
                endpoint: DEFAULT_ENDPOINT,
                debounceMs: 280,
                timeoutMs: 10000,
                minimumQueryLength: 2,
                itemClass: "panel-picker__item",
                bodyClass: "panel-picker__body",
                emptyText: "Панели не найдены. Уточните адрес или назначение точки доступа.",
                shortQueryText: "Введите не менее двух символов.",
                loadingText: "Поиск…",
                errorText: "Не удалось выполнить поиск. Повторите попытку.",
                timeoutText: "Превышено время ожидания. Повторите поиск.",
                ...options,
            };
            this.bound = [];
            this.bind();
            this.bindRemoteSearch();
            this.updateSelection();
        }

        listen(node, event, handler) {
            if (!node) return;
            node.addEventListener(event, handler);
            this.bound.push([node, event, handler]);
        }

        bind() {
            const o = this.options;
            this.listen(o.openButton, "click", () => this.open());
            this.listen(o.closeButton, "click", () => this.close());
            this.listen(o.cancelButton, "click", () => this.close());
            this.listen(o.results, "change", () => this.updateSelection());
            this.listen(o.addButton, "click", () => this.addSelected());
            this.listen(o.manualContainer, "click", (event) => this.removeManual(event));
            this.documentKeyHandler = (event) => {
                if (event.key === "Escape" && o.root && !o.root.hidden) {
                    event.preventDefault();
                    this.close();
                }
            };
            document.addEventListener("keydown", this.documentKeyHandler);
        }

        bindRemoteSearch() {
            const o = this.options;
            if (!global.SmartAutocomplete || !o.searchInput) {
                throw new Error("PanelPicker requires SmartAutocomplete");
            }
            this.remoteSearch = global.SmartAutocomplete.enhance(o.searchInput, {
                endpoint: o.endpoint,
                queryParameter: "query",
                searchButton: o.searchButton,
                debounceMs: o.debounceMs,
                timeoutMs: o.timeoutMs,
                minimumQueryLength: o.minimumQueryLength,
                renderMenu: false,
                onIdle: () => this.clearResults(o.shortQueryText),
                onLoading: () => {
                    this.setLoading(true);
                    this.setStatus(o.loadingText);
                },
                onLoaded: (items, context) => {
                    this.render(items, Number(context.payload?.total || 0));
                },
                onError: (error) => {
                    this.clearResults();
                    this.setStatus(error?.smartSearchReason === "timeout" ? o.timeoutText : o.errorText);
                },
                onFinally: () => this.setLoading(false),
            });
        }

        selectedCheckboxes() {
            return Array.from(this.options.results?.querySelectorAll("[data-picker-panel]:checked") || []);
        }

        updateSelection() {
            const o = this.options;
            const selected = this.selectedCheckboxes();
            if (o.selectionCount) o.selectionCount.textContent = String(selected.length);
            if (o.addButton) o.addButton.disabled = selected.length === 0;
            if (o.selection) o.selection.hidden = selected.length === 0;
            if (o.chips) {
                o.chips.innerHTML = selected.map((checkbox) => {
                    try {
                        const panel = decodePanel(checkbox);
                        return `<span>${escapeHtml(panel.address || "Адрес не указан")} · ${escapeHtml(panel.entrance || panel.name || "Точка доступа")}</span>`;
                    } catch (_error) {
                        return "";
                    }
                }).join("");
            }
            o.onSelectionChange?.(selected.length);
        }

        setStatus(text) {
            if (this.options.status) this.options.status.textContent = text;
        }

        setLoading(active) {
            if (this.options.searchButton) this.options.searchButton.disabled = active;
            this.options.root?.classList.toggle("is-searching", active);
        }

        clearResults(statusText = "") {
            this.options.results?.replaceChildren();
            if (statusText) this.setStatus(statusText);
            this.updateSelection();
        }

        render(items, total) {
            const o = this.options;
            if (!o.results) return;
            if (!items.length) {
                this.clearResults(o.emptyText);
                return;
            }
            this.setStatus(`Найдено: ${total}. Показаны первые ${items.length}.`);
            o.results.innerHTML = items.map((panel) => {
                const exists = Boolean(o.isAlreadySelected?.(panel.id));
                const disabled = exists || !panel.selectable;
                const reason = exists ? "Панель уже выбрана" : panel.unavailable_reason;
                const title = panel.entrance || panel.name || "Точка доступа";
                return `<label class="${escapeHtml(o.itemClass)} ${disabled ? "is-disabled" : ""}">
                    <span class="${escapeHtml(o.bodyClass)}">
                        <b>${escapeHtml(panel.address || "Адрес не указан")}</b>
                        <span>${escapeHtml(title)}</span>
                        <small>${escapeHtml(panel.mac || "MAC не указан")}</small>
                        ${reason ? `<em>${escapeHtml(reason)}</em>` : ""}
                    </span>
                    <span class="panel-picker__actions">
                        <span class="badge ${escapeHtml(panel.status_tone || "")}">${escapeHtml(panel.status_name || "")}</span>
                        <input type="checkbox" data-picker-panel data-panel="${encodeURIComponent(JSON.stringify(panel))}"
                            aria-label="Выбрать ${escapeHtml(panel.address || title)}" ${disabled ? "disabled" : ""}>
                    </span>
                </label>`;
            }).join("");
            this.updateSelection();
        }

        addSelected() {
            let added = 0;
            let duplicates = 0;
            this.selectedCheckboxes().forEach((checkbox) => {
                try {
                    const panel = decodePanel(checkbox);
                    if (this.options.isAlreadySelected?.(panel.id)) {
                        duplicates += 1;
                    } else if (this.options.addPanel?.(panel) !== false) {
                        added += 1;
                    } else {
                        duplicates += 1;
                    }
                } catch (error) {
                    console.error("panel_picker.invalid_item", error);
                }
            });
            this.options.onPanelsAdded?.({added, duplicates});
            this.close();
        }

        removeManual(event) {
            const o = this.options;
            const button = event.target.closest(o.removeSelector || "[data-remove-manual-panel]");
            if (!button || !o.manualContainer?.contains(button)) return;
            const item = button.closest(o.manualItemSelector || "[data-panel-source='manual']");
            if (!item) return;
            const panelId = item.dataset.panelId;
            item.remove();
            o.onPanelRemoved?.(panelId);
        }

        open() {
            const o = this.options;
            if (!o.root) return;
            o.root.hidden = false;
            o.root.setAttribute("aria-hidden", "false");
            document.body.classList.add("modal-open");
            window.setTimeout(() => o.searchInput?.focus(), 30);
            o.onOpen?.();
        }

        close() {
            const o = this.options;
            if (!o.root) return;
            this.remoteSearch?.cancel("closed");
            this.setLoading(false);
            o.root.hidden = true;
            o.root.setAttribute("aria-hidden", "true");
            document.body.classList.remove("modal-open");
            o.openButton?.focus();
            o.onClose?.();
        }

        destroy() {
            this.remoteSearch?.cancel("destroyed");
            this.bound.forEach(([node, event, handler]) => node.removeEventListener(event, handler));
            document.removeEventListener("keydown", this.documentKeyHandler);
        }
    }

    global.PanelPicker = PanelPicker;
})(window);
