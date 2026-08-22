(() => {
    const startForm = document.getElementById("messageForm");
    const messageText = document.getElementById("messageText");
    const messageSubmit = document.getElementById("messageSubmit");
    const parserState = document.querySelector(".message-parser-state");

    if (messageText && parserState) {
        const updateParserState = () => {
            const hasText = messageText.value.trim().length > 0;
            parserState.classList.toggle("has-text", hasText);
            parserState.lastChild.textContent = hasText
                ? "Сообщение готово"
                : "Готов к разбору";
        };
        messageText.addEventListener("input", updateParserState);
        updateParserState();
    }

    if (startForm && messageSubmit) {
        startForm.addEventListener("submit", () => {
            messageSubmit.disabled = true;
            messageSubmit.textContent = "Разбираем адрес и ключи…";
            parserState?.classList.add("is-processing");
        });
    }

    const correctionForm = document.getElementById("messageCorrectionForm");
    const addressInput = document.getElementById("messageAddressInput");

    document.querySelectorAll("[data-message-address]").forEach((button) => {
        button.addEventListener("click", () => {
            if (!addressInput || !correctionForm) {
                return;
            }
            addressInput.value = button.dataset.messageAddress || "";
            addressInput.dispatchEvent(new Event("input", { bubbles: true }));
            button.classList.add("is-loading");

            const submitButton = correctionForm.querySelector(
                "button[type='submit']"
            );
            if (submitButton) {
                submitButton.disabled = true;
                submitButton.textContent = "Проверяем панели…";
            }
            correctionForm.requestSubmit();
        });
    });

    if (correctionForm) {
        correctionForm.addEventListener("submit", () => {
            const submitButton = correctionForm.querySelector(
                "button[type='submit']"
            );
            if (submitButton) {
                submitButton.disabled = true;
                submitButton.textContent = "Обновляем подбор…";
            }
        });
    }

    const writeForm = document.getElementById("messageWriteForm");
    if (!writeForm) {
        return;
    }

    const panelCheckboxes = () => Array.from(document.querySelectorAll(
        "input[name='panel_ids_preview'][type='checkbox']"
    ));
    const panelList = document.getElementById("messagePanelList");
    const manualPanelList = document.getElementById("messageManualPanelList");
    const manualPanelSection = document.getElementById("manualPanelSection");
    const panelsEmpty = document.getElementById("messagePanelsEmpty");
    const selectAllButton = document.getElementById("select-all-panels");
    const clearAllButton = document.getElementById("clear-all-panels");
    const selectedCount = document.getElementById("selectedPanelCount");
    const automaticSummary = document.getElementById("automaticPanelsSummary");
    const manualSummary = document.getElementById("manualPanelsSummary");
    const selectedPanelsContainer = document.getElementById(
        "selectedPanelsContainer"
    );
    const writeButton = document.getElementById("messageWriteButton");
    const writeState = document.getElementById("messageWriteState");
    const typeSelectors = Array.from(
        document.querySelectorAll(".message-key-type-select")
    );
    const serverReady = writeForm.dataset.canWrite === "true";
    const hasUsedKeys = writeForm.dataset.hasUsedKeys === "true";
    const occupiedActionInputs = Array.from(
        document.querySelectorAll("select[name='occupied_actions']")
    );
    const keyCheckRows = Array.from(
        document.querySelectorAll(".message-key-check")
    );

    function unresolvedTypes() {
        return typeSelectors.filter((select) => !Number(select.value));
    }

    function selectedOccupiedAction() {
        const actions = occupiedActionInputs.map((input) => input.value).filter(Boolean);
        return actions.length === 1 ? actions[0] : actions.length ? "mixed" : "";
    }

    function updateKeyPanelStates(checkedPanels) {
        const selectedIds = new Set(
            checkedPanels.map((checkbox) => Number(checkbox.value))
        );
        keyCheckRows.forEach((row) => {
            const label = row.querySelector("[data-key-state-label]");
            if (!label || row.dataset.keyConflict === "true") return;
            const knownIds = new Set(
                (row.dataset.knownPanels || "")
                    .split(",")
                    .map((value) => Number(value))
                    .filter(Boolean)
            );
            const matchedCount = Array.from(selectedIds).filter((id) =>
                knownIds.has(id)
            ).length;
            const isUsed = row.dataset.keyUsed === "true";
            let text = "Свободен — готов к записи";
            let tone = "success";
            if (selectedIds.size && matchedCount === selectedIds.size) {
                text = selectedIds.size === 1
                    ? "Уже записан на выбранной панели"
                    : "Уже записан на всех выбранных панелях";
                tone = "info";
            } else if (matchedCount) {
                text = "Частично записан на выбранных панелях";
                tone = "warning";
            } else if (isUsed) {
                text = "Уже используется";
                tone = "warning";
            }
            label.textContent = text;
            label.classList.remove("success", "warning", "info", "error");
            label.classList.add(tone);
        });
    }

    function updateWriteState() {
        const checkedPanels = panelCheckboxes().filter(
            (checkbox) => checkbox.checked
        );
        const unresolved = unresolvedTypes();
        const occupiedAction = selectedOccupiedAction();

        updateKeyPanelStates(checkedPanels);

        if (selectedCount) {
            selectedCount.textContent = String(checkedPanels.length);
        }
        if (automaticSummary) {
            automaticSummary.textContent = String(checkedPanels.filter(
                (checkbox) => checkbox.dataset.panelSource === "automatic"
            ).length);
        }
        if (manualSummary) {
            manualSummary.textContent = String(checkedPanels.filter(
                (checkbox) => checkbox.dataset.panelSource === "manual"
            ).length);
        }
        if (panelsEmpty) {
            panelsEmpty.hidden = checkedPanels.length > 0;
        }

        document.querySelectorAll(".panel-option").forEach((option) => {
            const checkbox = option.querySelector(
                "input[name='panel_ids_preview']"
            );
            option.classList.toggle("is-selected", Boolean(checkbox?.checked));
        });

        let message = "Данные готовы к безопасной записи.";
        let ready = serverReady;

        if (!serverReady) {
            message = "Исправьте отмеченные выше данные и обновите подбор.";
        } else if (!checkedPanels.length) {
            ready = false;
            message = "Выберите хотя бы одну панель.";
        } else if (unresolved.length) {
            ready = false;
            message = "Выберите тип для каждого неоднозначного ключа.";
        } else if (hasUsedKeys && occupiedActionInputs.some((input) => !input.value)) {
            ready = false;
            message = "Для каждого занятого ключа выберите отдельное действие.";
        } else if (hasUsedKeys && occupiedAction === "reassign") {
            message = "Старое назначение будет удалено из CRM, после чего ключ будет записан на выбранный новый адрес и панели.";
        } else if (hasUsedKeys && occupiedAction === "add_panels") {
            message = "Текущее назначение сохранится. Ключ будет дополнительно записан на выбранные панели.";
        }

        if (writeButton) {
            writeButton.disabled = !ready;
            writeButton.textContent = ready
                ? writeButton.dataset.readyLabel
                : "Запись пока недоступна";
        }
        if (writeState) {
            writeState.textContent = message;
            writeState.classList.toggle("is-ready", ready);
        }
    }

    function setAllPanels(checked) {
        panelCheckboxes().forEach((checkbox) => {
            checkbox.checked = checked;
        });
        updateWriteState();
    }

    selectAllButton?.addEventListener("click", () => setAllPanels(true));
    clearAllButton?.addEventListener("click", () => setAllPanels(false));
    document.addEventListener("change", (event) => {
        if (event.target.matches("input[name='panel_ids_preview']")) {
            updateWriteState();
        }
    });

    const picker = document.getElementById("messagePanelPicker");
    const openPickerButton = document.getElementById("open-panel-picker");
    const closePickerButton = document.getElementById("close-panel-picker");
    const cancelPickerButton = document.getElementById("cancel-panel-picker");
    const panelSearch = document.getElementById("messagePanelSearch");
    const searchResults = document.getElementById("messagePanelSearchResults");
    const searchStatus = document.getElementById("messagePanelSearchStatus");
    const addSelectedButton = document.getElementById("add-selected-panels");
    const pickerCount = document.getElementById("messagePanelPickerCount");
    const pickerSelection = document.getElementById("messagePanelPickerSelection");
    const pickerChips = document.getElementById("messagePanelPickerChips");
    function escapeHtml(value) {
        const node = document.createElement("span");
        node.textContent = String(value ?? "");
        return node.innerHTML;
    }

    function panelAlreadySelected(panelId) {
        return Boolean(document.querySelector(
            `[data-panel-id="${CSS.escape(String(panelId))}"]`
        ));
    }

    function createManualPanel(panel) {
        if (!manualPanelList || panelAlreadySelected(panel.id)) return;
        const article = document.createElement("article");
        article.className = "panel-option is-selected";
        article.dataset.panelId = String(panel.id);
        article.dataset.panelSource = "manual";
        const checkboxId = `manual-panel-${String(panel.id).replace(/[^a-zA-Z0-9_-]/g, "-")}`;
        article.innerHTML = `
            <label class="panel-card__content" for="${escapeHtml(checkboxId)}">
                <span class="panel-option-body">
                    <span class="panel-option-title">${escapeHtml(panel.entrance || panel.name || "Точка доступа")}</span>
                    <span class="panel-option-meta">${escapeHtml(panel.address || "Адрес не указан")}</span>
                    <span class="panel-option-mac">${escapeHtml(panel.mac || "MAC не указан")}</span>
                    <span class="message-panel-source is-manual">Добавлена вручную</span>
                </span>
            </label>
            <div class="panel-card__actions">
                <input class="panel-card__checkbox" id="${escapeHtml(checkboxId)}" type="checkbox" name="panel_ids_preview" value="${escapeHtml(panel.id)}" data-panel-source="manual" aria-label="Выбрать панель ${escapeHtml(panel.entrance || panel.name || panel.address || panel.id)}" checked>
                <button type="button" class="message-manual-panel-remove" data-remove-manual-panel aria-label="Удалить из выбранных" title="Удалить из выбранных">×</button>
            </div>`;
        manualPanelList.appendChild(article);
        if (manualPanelSection) manualPanelSection.hidden = false;
        if (panelsEmpty) panelsEmpty.hidden = true;
    }

    new window.PanelPicker({
        endpoint: "/message/panels/search",
        root: picker,
        openButton: openPickerButton,
        closeButton: closePickerButton,
        cancelButton: cancelPickerButton,
        searchInput: panelSearch,
        status: searchStatus,
        results: searchResults,
        selection: pickerSelection,
        selectionCount: pickerCount,
        chips: pickerChips,
        addButton: addSelectedButton,
        manualContainer: manualPanelList,
        manualItemSelector: ".panel-option",
        itemClass: "message-panel-picker__item",
        bodyClass: "message-panel-picker__body",
        debounceMs: 260,
        isAlreadySelected: panelAlreadySelected,
        addPanel: createManualPanel,
        onPanelsAdded: () => updateWriteState(),
        onPanelRemoved: () => {
            if (!manualPanelList?.querySelector(".panel-option") && manualPanelSection) {
                manualPanelSection.hidden = true;
            }
            updateWriteState();
        },
    });

    typeSelectors.forEach((select) => {
        select.addEventListener("change", () => {
            if (!Number(select.value) || !correctionForm) return;
            select.classList.add("is-loading");
            correctionForm.requestSubmit();
        });
    });
    occupiedActionInputs.forEach((input) => {
        input.addEventListener("change", updateWriteState);
    });

    let writeInFlight = false;
    writeForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        updateWriteState();
        if (writeInFlight || writeButton?.disabled) return;

        const checkedPanels = panelCheckboxes().filter(
            (checkbox) => checkbox.checked
        );
        const keyCount = Number(writeForm.dataset.keyCount || 0);
        const apartment = writeForm.dataset.apartment || "—";
        const occupiedAction = selectedOccupiedAction();
        let confirmation = false;
        try {
            let title = "Подтвердите запись ключей";
            let message = `Записать ключей: ${keyCount}\n` +
                `Панелей: ${checkedPanels.length}\n` +
                `Квартира: ${apartment}\n\n` +
                "После подтверждения начнётся фактическая запись.";
            let confirmText = "Записать ключи";
            if (occupiedAction === "reassign") {
                title = "Подтвердите переназначение ключа";
                message = "Старое назначение будет удалено из CRM, после чего ключ будет записан на выбранный новый адрес и панели.";
                confirmText = "Переназначить и записать";
            } else if (occupiedAction === "add_panels") {
                title = "Подтвердите дополнительный доступ";
                message = "Текущее назначение сохранится. Ключ будет дополнительно записан на выбранные панели.";
                confirmText = "Добавить на панели";
            }
            confirmation = await window.showDangerConfirm({
                title,
                message,
                confirmText,
                cancelText: "Вернуться к проверке",
                source: writeButton,
            });
        } catch (error) {
            console.error("key_write.confirmation.error", error);
            await window.showAlert?.({
                title: "Не удалось открыть подтверждение",
                message: "Обновите страницу и повторите попытку.",
                source: writeButton,
            });
            updateWriteState();
            return;
        }

        if (!confirmation) {
            return;
        }

        selectedPanelsContainer?.replaceChildren();
        checkedPanels.forEach((checkbox) => {
            const hiddenInput = document.createElement("input");
            hiddenInput.type = "hidden";
            hiddenInput.name = "panel_ids";
            hiddenInput.value = checkbox.value;
            selectedPanelsContainer?.appendChild(hiddenInput);

            const sourceInput = document.createElement("input");
            sourceInput.type = "hidden";
            sourceInput.name = checkbox.dataset.panelSource === "manual"
                ? "manual_panel_ids"
                : "automatic_panel_ids";
            sourceInput.value = checkbox.value;
            selectedPanelsContainer?.appendChild(sourceInput);
        });

        writeInFlight = true;
        if (writeButton) {
            writeButton.disabled = true;
            writeButton.textContent = "Запись выполняется…";
        }
        if (window.GlobalLoader?.submitForm) {
            window.GlobalLoader.submitForm(writeForm);
        } else {
            writeForm.submit();
        }
    });

    window.addEventListener("pageshow", () => {
        writeInFlight = false;
        updateWriteState();
    });

    updateWriteState();
})();
