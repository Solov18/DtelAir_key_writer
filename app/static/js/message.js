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
        document.querySelectorAll("input[name='occupied_action']")
    );
    const keyCheckRows = Array.from(
        document.querySelectorAll(".message-key-check")
    );

    function unresolvedTypes() {
        return typeSelectors.filter((select) => !Number(select.value));
    }

    function selectedOccupiedAction() {
        return occupiedActionInputs.find((input) => input.checked)?.value || "";
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
        } else if (hasUsedKeys && !occupiedAction) {
            ready = false;
            message = "Ключ уже используется — выберите переназначение или добавление на новые панели.";
        } else if (hasUsedKeys && occupiedAction === "reassign") {
            message = "Будет создано новое назначение; старые панели останутся без изменений.";
        } else if (hasUsedKeys && occupiedAction === "add_panels") {
            message = "Текущее назначение сохранится; запросы уйдут только на недостающие панели.";
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
    let pickerRequest = null;
    let pickerTimer = 0;

    function escapeHtml(value) {
        const node = document.createElement("span");
        node.textContent = String(value ?? "");
        return node.innerHTML;
    }

    function selectedPickerPanels() {
        return Array.from(searchResults?.querySelectorAll(
            "input[data-picker-panel]:checked"
        ) || []);
    }

    function updatePickerState() {
        const selected = selectedPickerPanels();
        const count = selected.length;
        if (pickerCount) pickerCount.textContent = String(count);
        if (addSelectedButton) addSelectedButton.disabled = count === 0;
        if (pickerSelection) pickerSelection.hidden = count === 0;
        if (pickerChips) {
            pickerChips.innerHTML = selected.map((checkbox) => {
                try {
                    const panel = JSON.parse(decodeURIComponent(checkbox.dataset.panel || "%7B%7D"));
                    return `<span>${escapeHtml(panel.address || "Адрес не указан")} · ${escapeHtml(panel.entrance || panel.name || "Точка доступа")}</span>`;
                } catch (_error) {
                    return "";
                }
            }).join("");
        }
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
        picker.hidden = true;
        picker.setAttribute("aria-hidden", "true");
        document.body.classList.remove("modal-open");
        openPickerButton?.focus();
    }

    function panelAlreadySelected(panelId) {
        return Boolean(document.querySelector(
            `[data-panel-id="${CSS.escape(String(panelId))}"]`
        ));
    }

    function renderPanelSearch(items, total) {
        if (!searchResults || !searchStatus) return;
        if (!items.length) {
            searchResults.replaceChildren();
            searchStatus.textContent = "Панели не найдены. Уточните адрес или назначение точки доступа.";
            updatePickerState();
            return;
        }
        searchStatus.textContent = `Найдено: ${total}. Показаны первые ${items.length}.`;
        searchResults.innerHTML = items.map((panel) => {
            const exists = panelAlreadySelected(panel.id);
            const disabled = exists || !panel.selectable;
            const reason = exists ? "Панель уже выбрана" : panel.unavailable_reason;
            const title = panel.entrance || panel.name || "Точка доступа";
            return `
                <label class="message-panel-picker__item ${disabled ? "is-disabled" : ""}">
                    <span class="message-panel-picker__body">
                        <b>${escapeHtml(panel.address || "Адрес не указан")}</b>
                        <span>${escapeHtml(title)}</span>
                        <small>${escapeHtml(panel.mac || "MAC не указан")}</small>
                    </span>
                    <span class="badge ${escapeHtml(panel.status_tone)}">${escapeHtml(panel.status_name)}</span>
                    <input type="checkbox" data-picker-panel
                        data-panel="${encodeURIComponent(JSON.stringify(panel))}"
                        aria-label="Выбрать ${escapeHtml(panel.address || title)}"
                        ${disabled ? "disabled" : ""}>
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
        if (searchStatus) searchStatus.textContent = "Ищем панели…";
        try {
            const response = await fetch(
                `/message/panels/search?query=${encodeURIComponent(query)}`,
                { signal: pickerRequest.signal, globalLoader: false }
            );
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const payload = await response.json();
            renderPanelSearch(payload.items || [], Number(payload.total || 0));
        } catch (error) {
            if (error.name === "AbortError") return;
            console.error("message.panel_search.error", error);
            searchResults?.replaceChildren();
            if (searchStatus) searchStatus.textContent = "Не удалось выполнить поиск. Повторите попытку.";
            updatePickerState();
        }
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

    openPickerButton?.addEventListener("click", openPicker);
    closePickerButton?.addEventListener("click", closePicker);
    cancelPickerButton?.addEventListener("click", closePicker);
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && picker && !picker.hidden) {
            event.preventDefault();
            closePicker();
        }
    });
    panelSearch?.addEventListener("input", () => {
        window.clearTimeout(pickerTimer);
        pickerTimer = window.setTimeout(searchPanels, 260);
    });
    searchResults?.addEventListener("change", updatePickerState);
    addSelectedButton?.addEventListener("click", () => {
        selectedPickerPanels().forEach((checkbox) => {
            try {
                createManualPanel(JSON.parse(decodeURIComponent(checkbox.dataset.panel || "%7B%7D")));
            } catch (error) {
                console.error("message.panel_picker.invalid_item", error);
            }
        });
        updateWriteState();
        closePicker();
    });
    manualPanelList?.addEventListener("click", (event) => {
        const removeButton = event.target.closest("[data-remove-manual-panel]");
        if (!removeButton) return;
        removeButton.closest(".panel-option")?.remove();
        if (!manualPanelList.querySelector(".panel-option") && manualPanelSection) {
            manualPanelSection.hidden = true;
        }
        updateWriteState();
    });

    typeSelectors.forEach((select) => {
        select.addEventListener("change", () => {
            const hiddenInput = writeForm.querySelector(
                `[data-key-type-for="${CSS.escape(select.dataset.keyNumber)}"]`
            );
            if (hiddenInput) {
                hiddenInput.value = select.value;
            }
            updateWriteState();
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
                message = "Ключ уже назначен другому адресу. Его текущее назначение в CRM будет заменено новым. Запись на старых панелях сохранится, пока ключ не будет удалён с них отдельной операцией";
                confirmText = "Переназначить и записать";
            } else if (occupiedAction === "add_panels") {
                title = "Подтвердите дополнительный доступ";
                message = "Ключ уже используется. Он будет дополнительно записан на выбранные панели без изменения текущего назначения";
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

        console.info("key_write.submit", {
            keyCount,
            panelIds: checkedPanels.map((checkbox) => checkbox.value),
        });
        writeInFlight = true;
        if (writeButton) {
            writeButton.disabled = true;
            writeButton.textContent = "Запись выполняется…";
        }
        // Keep the write page visible while the server communicates with CRM.
        // This flow deliberately does not use the global blocking overlay.
        window.suppressGlobalLoaderForNextNavigation?.();
        writeForm.submit();
    });

    window.addEventListener("pageshow", () => {
        writeInFlight = false;
        updateWriteState();
    });

    updateWriteState();
})();
