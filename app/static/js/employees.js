(() => {
    document.querySelectorAll("[data-employee-choose-other]").forEach((button) => {
        button.addEventListener("click", () => {
            const input = document.querySelector("#issue-key input[name='key_value']");
            if (!input) return;
            input.value = "";
            input.focus();
            input.scrollIntoView({behavior: "smooth", block: "center"});
        });
    });
    const normalize = window.smartSearchNormalize || ((value) => (
        String(value || "")
            .normalize("NFKC")
            .toLocaleLowerCase("ru-RU")
            .replace(/ё/g, "е")
            .replace(/[^\p{L}\p{N}]+/gu, "")
    ));

    function openModal(modal) {
        if (!modal) {
            return;
        }
        if (window.AppModal) {
            window.AppModal.open(modal, document.activeElement);
            return;
        }

        modal.classList.add("is-open");
        modal.setAttribute("aria-hidden", "false");
        document.body.classList.add("employee-modal-open");

        const firstField = modal.querySelector("input, select, textarea");
        window.setTimeout(() => firstField?.focus(), 50);
    }

    document.querySelectorAll("[data-open-employee-modal]").forEach((trigger) => {
        trigger.addEventListener("click", (event) => {
            event.preventDefault();
            event.stopPropagation();

            const selectedOnly = trigger.dataset.selectedOnly;
            const selectedRow = document.querySelector(
                "[data-employee-row].is-selected"
            );

            if (
                selectedOnly &&
                !selectedRow?.dataset.href?.includes(
                    `selected_employee_id=${selectedOnly}`
                )
            ) {
                const targetRow = Array.from(
                    document.querySelectorAll("[data-employee-row]")
                ).find((row) => (
                    row.dataset.href?.includes(
                        `selected_employee_id=${selectedOnly}`
                    )
                ));

                if (targetRow?.dataset.href) {
                    const separator = targetRow.dataset.href.includes("?")
                        ? "&"
                        : "?";
                    window.location.assign(
                        `${targetRow.dataset.href}${separator}edit=1`
                    );
                }
                return;
            }

            openModal(
                document.getElementById(trigger.dataset.openEmployeeModal)
            );
        });
    });

    document.querySelectorAll("[data-employee-row]").forEach((row) => {
        const activate = () => {
            if (row.dataset.href) {
                window.location.assign(row.dataset.href);
            }
        };

        row.addEventListener("click", (event) => {
            if (event.target.closest("a, button, input, select, textarea, form")) {
                return;
            }
            activate();
        });

        row.addEventListener("keydown", (event) => {
            if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                activate();
            }
        });
    });

    const selectedRow = document.querySelector(
        "[data-employee-row].is-selected"
    );
    if (selectedRow) {
        selectedRow.scrollIntoView({ block: "nearest" });
    }

    const params = new URLSearchParams(window.location.search);
    if (params.get("edit") === "1") {
        openModal(document.getElementById("employeeEditModal"));
        params.delete("edit");
        const cleanQuery = params.toString();
        window.history.replaceState(
            {},
            "",
            `${window.location.pathname}${cleanQuery ? `?${cleanQuery}` : ""}`
        );
    }

    document.querySelectorAll("[data-local-smart-filter]").forEach((input) => {
        const selector = input.dataset.localSmartFilter;
        input.addEventListener("input", () => {
            const query = normalize(input.value);
            document.querySelectorAll(selector).forEach((item) => {
                const haystack = normalize(
                    item.dataset.search || item.textContent
                );
                item.hidden = Boolean(query) && !haystack.includes(query);
            });
        });
    });
    const issueForm = document.getElementById("employeeIssueKeyForm");
    const panelPickerRoot = document.getElementById("employeePanelPicker");
    if (issueForm && panelPickerRoot && window.PanelPicker) {
        const selectedContainer = issueForm.querySelector("[data-employee-selected-panels]");
        const count = issueForm.querySelector("[data-employee-panel-count]");
        const empty = issueForm.querySelector("[data-employee-panel-empty]");
        const scope = issueForm.querySelector("[data-employee-panel-scope]");
        const allPanels = issueForm.querySelector("[data-employee-all-panels]");

        const selectedIds = () => Array.from(selectedContainer.querySelectorAll('input[name="panel_ids"]')).map((node) => node.value);
        const updatePanelState = () => {
            const ids = selectedIds();
            count.textContent = String(ids.length);
            empty.hidden = ids.length > 0 || allPanels.checked;
            scope.value = allPanels.checked ? "all" : "selected";
            selectedContainer.classList.toggle("is-all", allPanels.checked);
            selectedContainer.querySelectorAll("button, input").forEach((node) => { node.disabled = allPanels.checked; });
        };
        const hasPanel = (id) => selectedContainer.querySelector(`[data-panel-id="${CSS.escape(String(id))}"]`) !== null;
        const addPanel = (panel) => {
            if (hasPanel(panel.id)) return false;
            const item = document.createElement("article");
            item.className = "employee-selected-panel";
            item.dataset.panelId = String(panel.id);
            item.dataset.panelSource = "manual";
            item.innerHTML = `<input type="hidden" name="panel_ids" value="${String(panel.id).replace(/[^0-9]/g, "")}">
                <div><b></b><span></span><code></code></div>
                <button type="button" data-remove-manual-panel title="Удалить из выбранных" aria-label="Удалить из выбранных">×</button>`;
            item.querySelector("b").textContent = panel.address || "Адрес не указан";
            item.querySelector("span").textContent = panel.entrance || panel.name || "Точка доступа";
            item.querySelector("code").textContent = panel.mac || "MAC не указан";
            selectedContainer.append(item);
            updatePanelState();
            return true;
        };

        allPanels.addEventListener("change", async () => {
            if (allPanels.checked) {
                const confirmed = await window.showDangerConfirm?.({
                    title: "Записать ключ на все панели?",
                    text: "Ключ будет физически отправлен на каждую активную панель системы. Используйте этот режим только для служебного ключа с полным доступом.",
                    confirmText: "Использовать все панели",
                    cancelText: "Отмена",
                    source: allPanels,
                });
                if (!confirmed) allPanels.checked = false;
            }
            updatePanelState();
        });

        new window.PanelPicker({
            endpoint: "/message/panels/search",
            root: panelPickerRoot,
            openButton: document.getElementById("openEmployeePanelPicker"),
            closeButton: document.getElementById("closeEmployeePanelPicker"),
            cancelButton: document.getElementById("cancelEmployeePanelPicker"),
            searchInput: document.getElementById("employeePanelSearch"),
            searchButton: document.getElementById("findEmployeePanels"),
            status: document.getElementById("employeePanelSearchStatus"),
            results: document.getElementById("employeePanelSearchResults"),
            selection: document.getElementById("employeePanelPickerSelection"),
            selectionCount: document.getElementById("employeePanelPickerCount"),
            chips: document.getElementById("employeePanelPickerChips"),
            addButton: document.getElementById("addEmployeePanels"),
            manualContainer: selectedContainer,
            manualItemSelector: ".employee-selected-panel",
            itemClass: "employee-panel-picker__item",
            bodyClass: "employee-panel-picker__body",
            isAlreadySelected: hasPanel,
            addPanel,
            onPanelsAdded: updatePanelState,
            onPanelRemoved: updatePanelState,
        });

        issueForm.addEventListener("submit", async (event) => {
            if (!allPanels.checked && selectedIds().length === 0) {
                event.preventDefault();
                await window.showAlert?.({title: "Панели не выбраны", text: "Выберите панели для физической записи ключа или явно включите запись на все панели.", source: issueForm.querySelector("button[type=submit]")});
                document.getElementById("openEmployeePanelPicker")?.focus();
            }
        });
        updatePanelState();
    }
})();
