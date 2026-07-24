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

    function unresolvedTypes() {
        return typeSelectors.filter((select) => !Number(select.value));
    }

    function updateWriteState() {
        const checkedPanels = panelCheckboxes.filter(
            (checkbox) => checkbox.checked
        );
        const unresolved = unresolvedTypes();

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

    writeForm.addEventListener("submit", (event) => {
        updateWriteState();
        if (writeButton?.disabled) {
            event.preventDefault();
            return;
        }

        const checkedPanels = panelCheckboxes.filter(
            (checkbox) => checkbox.checked
        );
        const keyCount = Number(writeForm.dataset.keyCount || 0);
        const apartment = writeForm.dataset.apartment || "—";
        const confirmation = window.confirm(
            `Записать ключей: ${keyCount}\n` +
            `Панелей: ${checkedPanels.length}\n` +
            `Квартира: ${apartment}\n\n` +
            "Продолжить фактическую запись?"
        );

        if (!confirmation) {
            event.preventDefault();
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

        if (writeButton) {
            writeButton.disabled = true;
            writeButton.textContent = "Запись выполняется…";
        }
    });

    updateWriteState();
})();
