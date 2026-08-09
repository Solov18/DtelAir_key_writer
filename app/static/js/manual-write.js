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
    let pickerRequest = null;
    let pickerTimer = null;
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
        const ready = selected > 0 && Boolean(confirmation?.checked);
        if (submit) submit.disabled = !ready || writeInFlight;
        if (hint) {
            hint.textContent = selected === 0
                ? "Выберите хотя бы одну панель."
                : confirmation?.checked
                    ? `К записи готовы ${selected} пан. Основной адрес назначения не изменится.`
                    : "Подтвердите проверку данных, чтобы продолжить.";
        }
    }

    function selectedPickerPanels() {
        return Array.from(searchResults?.querySelectorAll("[data-picker-panel]:checked") || []);
    }

    function updatePickerState() {
        const selected = selectedPickerPanels();
        if (pickerCount) pickerCount.textContent = String(selected.length);
        if (addSelectedButton) addSelectedButton.disabled = selected.length === 0;
        if (pickerSelection) pickerSelection.hidden = selected.length === 0;
        if (pickerChips) {
            pickerChips.innerHTML = selected.map((checkbox) => {
                const panel = JSON.parse(decodeURIComponent(checkbox.dataset.panel || "%7B%7D"));
                return `<span>${escapeHtml(panel.address || "Панель")} · ${escapeHtml(panel.entrance || panel.name || panel.id)}</span>`;
            }).join("");
        }
    }

    function renderPanelSearch(items, total) {
        if (!searchResults || !searchStatus) return;
        if (!items.length) {
            searchResults.replaceChildren();
            searchStatus.textContent = "Панели не найдены. Уточните адрес или название точки доступа.";
            updatePickerState();
            return;
        }
        searchStatus.textContent = `Найдено: ${total}. Показаны первые ${items.length}.`;
        searchResults.innerHTML = items.map((panel) => {
            const exists = panelAlreadySelected(panel.id);
            const disabled = exists || !panel.selectable;
            const reason = exists ? "Панель уже выбрана" : panel.unavailable_reason;
            const title = panel.entrance || panel.name || "Точка доступа";
            return `<label class="manual-panel-picker__item ${disabled ? "is-disabled" : ""}">
                <span class="manual-panel-picker__body">
                    <b>${escapeHtml(panel.address || "Адрес не указан")}</b>
                    <span>${escapeHtml(title)}</span>
                    <small>${escapeHtml(panel.mac || "MAC не указан")}</small>
                </span>
                <span class="badge ${escapeHtml(panel.status_tone)}">${escapeHtml(panel.status_name)}</span>
                <input type="checkbox" data-picker-panel data-panel="${encodeURIComponent(JSON.stringify(panel))}" ${disabled ? "disabled" : ""}>
                ${reason ? `<em>${escapeHtml(reason)}</em>` : ""}
            </label>`;
        }).join("");
        updatePickerState();
    }

    async function searchPanels() {
        const query = panelSearch?.value.trim() || "";
        if (query.length < 2) {
            searchResults?.replaceChildren();
            if (searchStatus) searchStatus.textContent = "Введите не менее двух символов.";
            updatePickerState();
            return;
        }
        pickerRequest?.abort();
        pickerRequest = new AbortController();
        if (searchStatus) searchStatus.textContent = "Поиск…";
        if (findPanelsButton) findPanelsButton.disabled = true;
        const timeout = window.setTimeout(() => pickerRequest?.abort(), 10000);
        try {
            const response = await fetch(`/message/panels/search?query=${encodeURIComponent(query)}`, {
                signal: pickerRequest.signal,
                globalLoader: false,
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const payload = await response.json();
            renderPanelSearch(payload.items || [], Number(payload.total || 0));
        } catch (error) {
            if (error.name === "AbortError") {
                if (searchStatus) searchStatus.textContent = "Поиск остановлен или превышено время ожидания. Повторите попытку.";
            } else {
                console.error("manual.panel_search.error", error);
                if (searchStatus) searchStatus.textContent = "Не удалось выполнить поиск. Основная страница остаётся доступной.";
            }
            searchResults?.replaceChildren();
            updatePickerState();
        } finally {
            window.clearTimeout(timeout);
            if (findPanelsButton) findPanelsButton.disabled = false;
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

    function openPicker() {
        if (!picker) return;
        picker.hidden = false;
        picker.setAttribute("aria-hidden", "false");
        document.body.classList.add("modal-open");
        window.setTimeout(() => panelSearch?.focus(), 30);
    }

    function closePicker() {
        if (!picker) return;
        pickerRequest?.abort();
        picker.hidden = true;
        picker.setAttribute("aria-hidden", "true");
        document.body.classList.remove("modal-open");
        openPickerButton?.focus();
    }

    form.addEventListener("change", (event) => {
        if (event.target.matches('input[name="panel_ids"], #confirmManualWrite')) updateState();
    });
    selectAll?.addEventListener("click", () => {
        panelCheckboxes("automatic").forEach((item) => { item.checked = true; });
        updateState();
    });
    clearAll?.addEventListener("click", () => {
        panelCheckboxes("automatic").forEach((item) => { item.checked = false; });
        updateState();
    });
    manualList?.addEventListener("click", (event) => {
        const button = event.target.closest("[data-remove-manual-panel]");
        if (!button) return;
        button.closest(".manual-panel-option")?.remove();
        if (!manualList.querySelector(".manual-panel-option") && manualSection) manualSection.hidden = true;
        updateState();
    });

    openPickerButton?.addEventListener("click", openPicker);
    closePickerButton?.addEventListener("click", closePicker);
    cancelPickerButton?.addEventListener("click", closePicker);
    findPanelsButton?.addEventListener("click", searchPanels);
    panelSearch?.addEventListener("input", () => {
        window.clearTimeout(pickerTimer);
        pickerTimer = window.setTimeout(searchPanels, 280);
    });
    panelSearch?.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
            event.preventDefault();
            event.stopPropagation();
            searchPanels();
        }
    });
    searchResults?.addEventListener("change", updatePickerState);
    addSelectedButton?.addEventListener("click", async () => {
        let added = 0;
        let duplicates = 0;
        selectedPickerPanels().forEach((checkbox) => {
            const panel = JSON.parse(decodeURIComponent(checkbox.dataset.panel || "%7B%7D"));
            if (createManualPanel(panel)) added += 1;
            else duplicates += 1;
        });
        updateState();
        closePicker();
        if (!added && duplicates) {
            await window.showAlert?.({title: "Панель уже выбрана", message: "Выбранные панели уже присутствуют в списке.", source: openPickerButton});
        }
    });
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && picker && !picker.hidden) {
            event.preventDefault();
            closePicker();
        }
    });

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const checkedPanels = panelCheckboxes().filter((item) => item.checked);
        if (writeInFlight || !checkedPanels.length || !confirmation?.checked) {
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
        let pageResponse = null;
        try {
            pageResponse = await window.submitHtmlFormWithLoader(form, {submitter: submit});
        } catch (error) {
            console.error("key_write.request.error", error);
            await window.showAlert({
                title: "Запись не завершена",
                message: error?.message || "Не удалось получить ответ сервера.",
                source: submit,
            });
        } finally {
            writeInFlight = false;
            if (form.isConnected) updateState();
            console.info("key_write.loader.closed");
        }
        if (pageResponse) window.renderHtmlResponse(pageResponse);
    });
    window.addEventListener("pageshow", () => {
        writeInFlight = false;
        updateState();
    });
    updateState();
})();
