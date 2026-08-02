(() => {
    const startForm = document.getElementById("messageForm");
    const messageText = document.getElementById("messageText");
    const messageSubmit = document.getElementById("messageSubmit");
    const parserState = document.querySelector(".message-parser-state");
    const exampleButton = document.querySelector("[data-message-example]");

    const exampleText = [
        "Прописать 2 ключа №39107, №39300",
        "Сочи, ул. Тепличная, д. 65, корп. 1, кв. 10",
        "+7 999 000-00-00",
    ].join("\n");

    if (exampleButton && messageText) {
        exampleButton.addEventListener("click", () => {
            messageText.value = exampleText;
            messageText.dispatchEvent(new Event("input", { bubbles: true }));
            messageText.focus();
            messageText.setSelectionRange(
                messageText.value.length,
                messageText.value.length
            );
        });
    }

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

    const panelCheckboxes = Array.from(
        document.querySelectorAll(
            "input[name='panel_ids_preview'][type='checkbox']"
        )
    );
    const selectAllButton = document.getElementById("select-all-panels");
    const clearAllButton = document.getElementById("clear-all-panels");
    const selectedCount = document.getElementById("selectedPanelCount");
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
        const checkedPanels = panelCheckboxes.filter(
            (checkbox) => checkbox.checked
        );
        const unresolved = unresolvedTypes();
        const occupiedAction = selectedOccupiedAction();

        updateKeyPanelStates(checkedPanels);

        if (selectedCount) {
            selectedCount.textContent = String(checkedPanels.length);
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
        panelCheckboxes.forEach((checkbox) => {
            checkbox.checked = checked;
        });
        updateWriteState();
    }

    selectAllButton?.addEventListener("click", () => setAllPanels(true));
    clearAllButton?.addEventListener("click", () => setAllPanels(false));
    panelCheckboxes.forEach((checkbox) => {
        checkbox.addEventListener("change", updateWriteState);
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

        const checkedPanels = panelCheckboxes.filter(
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
