(() => {
    const form = document.getElementById("manualWriteForm");
    if (!form) return;

    const automaticList = document.getElementById("automaticPanelList");
    const manualList = document.getElementById("manualPanelList");
    const manualSection = document.getElementById("manualPanelSection");
    const selectAll = document.getElementById("select-all-panels");
    const clearAll = document.getElementById("clear-all-panels");
    const automaticCount = document.getElementById("automaticPanelCount");
    const manualCount = document.getElementById("manualPanelCount");
    const totalCount = document.getElementById("selectedPanelCount");
    const sourceContainer = document.getElementById("selectedPanelSources");
    const confirmation = document.getElementById("confirmManualWrite");
    const submit = document.getElementById("manualWriteButton");
    const hint = document.getElementById("manualSubmitHint");
    const occupiedContainer = form.querySelector("[data-occupied-key]");
    const occupiedActions = Array.from(form.querySelectorAll('input[name="occupied_action"]'));

    const picker = document.getElementById("manualPanelPicker");
    const openPickerButton = document.getElementById("open-manual-panel-picker");
    const closePickerButton = document.getElementById("close-manual-panel-picker");
    const cancelPickerButton = document.getElementById("cancel-manual-panel-picker");
    const findPanelsButton = document.getElementById("find-manual-panels");
    const panelSearch = document.getElementById("manualPanelSearch");
    const searchStatus = document.getElementById("manualPanelSearchStatus");
    const searchResults = document.getElementById("manualPanelSearchResults");
    const pickerSelection = document.getElementById("manualPanelPickerSelection");
    const pickerCount = document.getElementById("manualPanelPickerCount");
    const pickerChips = document.getElementById("manualPanelPickerChips");
    const addSelectedButton = document.getElementById("add-manual-panels");
    let writeInFlight = false;

    const escapeHtml = (value) => String(value ?? "").replace(/[&<>'\"]/g, (symbol) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", "\"": "&quot;",
    }[symbol]));

    function panelCheckboxes(source = "") {
        const selector = source
            ? `input[name="panel_ids"][data-panel-source="${source}"]`
            : 'input[name="panel_ids"]';
        return Array.from(form.querySelectorAll(selector));
    }

    function panelAlreadySelected(panelId) {
        return Boolean(form.querySelector(`[data-panel-id="${CSS.escape(String(panelId))}"]`));
    }

    function updateState() {
        const autoSelected = panelCheckboxes("automatic").filter((item) => item.checked).length;
        const manualSelected = panelCheckboxes("manual").filter((item) => item.checked).length;
        const selected = autoSelected + manualSelected;
        if (automaticCount) automaticCount.textContent = String(autoSelected);
        if (manualCount) manualCount.textContent = String(manualSelected);
        if (totalCount) totalCount.textContent = String(selected);
        const occupiedAction = occupiedActions.find((item) => item.checked)?.value || "";
        const occupiedReady = !occupiedContainer || Boolean(occupiedAction);
        const ready = selected > 0 && Boolean(confirmation?.checked) && occupiedReady;
        if (submit) submit.disabled = !ready || writeInFlight;
        if (hint) {
            hint.textContent = selected === 0
                ? "Выберите хотя бы одну панель."
                : !occupiedReady
                    ? "Выберите действие для уже используемого ключа."
                : confirmation?.checked
                    ? `К записи готовы ${selected} пан. Основной адрес назначения не изменится.`
                    : "Подтвердите проверку данных, чтобы продолжить.";
        }
    }

    function createManualPanel(panel) {
        if (!manualList || panelAlreadySelected(panel.id)) return false;
        const article = document.createElement("article");
        article.className = "manual-panel-option manual-panel-option--manual";
        article.dataset.panelId = String(panel.id);
        article.dataset.panelSource = "manual";
        const checkboxId = `manual-write-panel-${String(panel.id).replace(/[^a-zA-Z0-9_-]/g, "-")}`;
        article.innerHTML = `<label class="manual-panel-content" for="${escapeHtml(checkboxId)}">
                <b class="manual-panel-name">${escapeHtml(panel.entrance || panel.name || "Точка доступа")}</b>
                <span class="manual-panel-address">${escapeHtml(panel.address || "Адрес не указан")}</span>
                <code class="manual-panel-mac">${escapeHtml(panel.mac || "MAC не указан")}</code>
                <span class="manual-panel-source is-manual">Добавлена вручную</span>
            </label>
            <div class="manual-panel-actions">
                <input class="manual-panel-checkbox" id="${escapeHtml(checkboxId)}" type="checkbox" name="panel_ids" value="${escapeHtml(panel.id)}" data-panel-source="manual" checked>
                <button type="button" class="manual-panel-remove" data-remove-manual-panel title="Удалить из выбранных" aria-label="Удалить из выбранных">×</button>
            </div>`;
        manualList.appendChild(article);
        if (manualSection) manualSection.hidden = false;
        return true;
    }

    form.addEventListener("change", (event) => {
        if (event.target.matches('input[name="panel_ids"], input[name="occupied_action"], #confirmManualWrite')) updateState();
    });
    selectAll?.addEventListener("click", () => {
        panelCheckboxes("automatic").forEach((item) => { item.checked = true; });
        updateState();
    });
    clearAll?.addEventListener("click", () => {
        panelCheckboxes("automatic").forEach((item) => { item.checked = false; });
        updateState();
    });
    new window.PanelPicker({
        endpoint: "/message/panels/search",
        root: picker,
        openButton: openPickerButton,
        closeButton: closePickerButton,
        cancelButton: cancelPickerButton,
        searchInput: panelSearch,
        searchButton: findPanelsButton,
        status: searchStatus,
        results: searchResults,
        selection: pickerSelection,
        selectionCount: pickerCount,
        chips: pickerChips,
        addButton: addSelectedButton,
        manualContainer: manualList,
        manualItemSelector: ".manual-panel-option",
        itemClass: "manual-panel-picker__item",
        bodyClass: "manual-panel-picker__body",
        isAlreadySelected: panelAlreadySelected,
        addPanel: createManualPanel,
        onPanelsAdded: async ({added, duplicates}) => {
            updateState();
            if (!added && duplicates) {
                await window.showAlert?.({
                    title: "Панель уже выбрана",
                    message: "Выбранные панели уже присутствуют в списке.",
                    source: openPickerButton,
                });
            }
        },
        onPanelRemoved: () => {
            if (!manualList?.querySelector(".manual-panel-option") && manualSection) {
                manualSection.hidden = true;
            }
            updateState();
        },
    });

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const checkedPanels = panelCheckboxes().filter((item) => item.checked);
        const occupiedAction = occupiedActions.find((item) => item.checked)?.value || "";
        if (writeInFlight || !checkedPanels.length || !confirmation?.checked || (occupiedContainer && !occupiedAction)) {
            updateState();
            return;
        }
        let confirmed = true;
        if (occupiedAction === "reassign") {
            confirmed = await window.showDangerConfirm({
                title: "Переназначить ключ?",
                message: "Старое назначение будет удалено из CRM, после чего ключ будет записан на выбранный новый адрес и панели.",
                confirmText: "Переназначить и записать",
                cancelText: "Отмена",
                source: submit,
            });
        } else if (occupiedAction === "add_panels") {
            confirmed = await window.showConfirm({
                title: "Добавить доступ на панели?",
                message: "Текущее назначение сохранится. Ключ будет дополнительно записан на выбранные панели.",
                confirmText: "Добавить на панели",
                cancelText: "Отмена",
                source: submit,
            });
        }
        if (!confirmed) {
            updateState();
            return;
        }
        sourceContainer?.replaceChildren();
        checkedPanels.forEach((checkbox) => {
            const sourceInput = document.createElement("input");
            sourceInput.type = "hidden";
            sourceInput.name = checkbox.dataset.panelSource === "manual" ? "manual_panel_ids" : "automatic_panel_ids";
            sourceInput.value = checkbox.value;
            sourceContainer?.appendChild(sourceInput);
        });
        writeInFlight = true;
        if (submit) {
            submit.disabled = true;
            submit.textContent = "Запись выполняется…";
        }
        if (window.GlobalLoader?.submitForm) {
            window.GlobalLoader.submitForm(form);
        } else {
            form.submit();
        }
    });
    window.addEventListener("pageshow", () => {
        writeInFlight = false;
        updateState();
    });
    updateState();
})();
