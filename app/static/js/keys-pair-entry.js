(() => {
    const panel = document.querySelector("[data-key-pair-table]");
    if (!panel) return;

    const keyTypeId = Number(panel.dataset.keyTypeId || 0);
    const draftKey = panel.dataset.draftKey || `dtel-key-pairs-${keyTypeId}`;
    const rows = Array.from(panel.querySelectorAll(".keys-pair-row"));
    const savedCountElement = document.getElementById("savedCount");
    const pendingCountElement = document.getElementById("pendingCount");
    const progressBar = document.getElementById("scanProgressBar");
    const toast = document.getElementById("scanToast");
    const saveAllButton = panel.querySelector("[data-save-all]");
    const finishButton = panel.querySelector("[data-finish]");
    let toastTimer;

    const cleanHex = (value) => String(value || "").toUpperCase().replace(/[\s:-]/g, "");
    const validHex = (value) => /^[0-9A-F]{6,16}$/.test(cleanHex(value));
    const validNumber = (value) => /^[0-9]+$/.test(String(value || "").trim());

    function showToast(message, isError = false) {
        if (!toast) return;
        toast.textContent = message;
        toast.classList.toggle("is-error", isError);
        toast.classList.add("is-visible");
        window.clearTimeout(toastTimer);
        toastTimer = window.setTimeout(() => toast.classList.remove("is-visible"), 3200);
    }

    function loadDrafts() {
        try {
            return JSON.parse(localStorage.getItem(draftKey) || "{}") || {};
        } catch (_) {
            return {};
        }
    }

    function saveDrafts() {
        const drafts = {};
        rows.forEach((row) => {
            if (row.classList.contains("is-saved")) return;
            const number = row.querySelector(".key-number-input")?.value.trim() || "";
            const hex = row.querySelector(".key-hex-input")?.value.trim() || "";
            if (number || hex) drafts[row.dataset.rowIndex] = { number, hex };
        });
        if (Object.keys(drafts).length) {
            localStorage.setItem(draftKey, JSON.stringify(drafts));
        } else {
            localStorage.removeItem(draftKey);
        }
    }

    function updateSummary() {
        const saved = rows.filter((row) => row.classList.contains("is-saved")).length;
        if (savedCountElement) savedCountElement.textContent = String(saved);
        if (pendingCountElement) pendingCountElement.textContent = String(rows.length - saved);
        if (progressBar) progressBar.style.width = `${rows.length ? (saved / rows.length) * 100 : 100}%`;
        if (saveAllButton) saveAllButton.disabled = saved === rows.length;
    }

    function setState(row, state, message) {
        row.classList.remove("is-waiting", "is-dirty", "is-saving", "is-saved", "is-error");
        row.classList.add(`is-${state}`);
        const stateElement = row.querySelector(".key-scan-state");
        if (stateElement) stateElement.textContent = message;
    }

    function markDirty(row) {
        if (row.classList.contains("is-saved") || row.classList.contains("is-saving")) return;
        const number = row.querySelector(".key-number-input")?.value.trim() || "";
        const hex = row.querySelector(".key-hex-input")?.value.trim() || "";
        if (!number && !hex) {
            setState(row, "waiting", "Заполните номер и HEX");
        } else if (number && !hex) {
            setState(row, "waiting", "Ожидает HEX");
        } else if (!number && hex) {
            setState(row, "dirty", "Укажите номер ключа");
        } else if (!validNumber(number)) {
            setState(row, "dirty", "Номер — только цифры");
        } else if (!validHex(hex)) {
            setState(row, "dirty", "Нужен HEX 6–16 символов");
        } else {
            setState(row, "dirty", "Готов к сохранению");
        }
        saveDrafts();
    }

    async function saveRow(row) {
        if (row.classList.contains("is-saving") || row.classList.contains("is-saved")) return true;
        const numberInput = row.querySelector(".key-number-input");
        const hexInput = row.querySelector(".key-hex-input");
        const saveButton = row.querySelector(".key-pair-save");
        const number = numberInput?.value.trim() || "";
        const hex = cleanHex(hexInput?.value || "");

        if (!validNumber(number)) {
            setState(row, "error", "Укажите номер цифрами");
            numberInput?.focus();
            return false;
        }
        if (!validHex(hex)) {
            setState(row, "error", "Некорректный HEX");
            hexInput?.focus();
            return false;
        }

        setState(row, "saving", "Проверяем и сохраняем…");
        if (saveButton) saveButton.disabled = true;
        try {
            const response = await fetch("/keys/scan", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    key_type_id: keyTypeId,
                    number,
                    hex_value: hex,
                }),
            });
            const contentType = response.headers.get("content-type") || "";
            const payload = contentType.includes("application/json") ? await response.json() : null;
            if (!response.ok || !payload?.ok) {
                throw new Error(payload?.error || "Сохранение сейчас недоступно.");
            }

            if (hexInput) hexInput.value = payload.hex_value;
            if (numberInput) numberInput.readOnly = true;
            if (hexInput) hexInput.readOnly = true;
            if (saveButton) {
                saveButton.textContent = "Сохранён";
                saveButton.disabled = true;
            }
            row.dataset.keyId = String(payload.key_id || "");
            setState(row, "saved", "Сохранён в базе");
            saveDrafts();
            updateSummary();
            showToast(`Ключ №${number} сохранён`);
            return true;
        } catch (error) {
            setState(row, "error", error.message || "Ошибка сохранения");
            if (saveButton) saveButton.disabled = false;
            showToast(error.message || "Не удалось сохранить ключ", true);
            return false;
        }
    }

    const drafts = loadDrafts();
    rows.forEach((row) => {
        const draft = drafts[row.dataset.rowIndex];
        const numberInput = row.querySelector(".key-number-input");
        const hexInput = row.querySelector(".key-hex-input");
        if (draft) {
            if (numberInput && !numberInput.readOnly) numberInput.value = draft.number || "";
            if (hexInput) hexInput.value = draft.hex || "";
        }
        numberInput?.addEventListener("input", () => markDirty(row));
        hexInput?.addEventListener("input", () => {
            if (hexInput) hexInput.value = cleanHex(hexInput.value);
            markDirty(row);
        });
        [numberInput, hexInput].forEach((input) => input?.addEventListener("keydown", (event) => {
            if (event.key === "Enter") {
                event.preventDefault();
                saveRow(row).then((saved) => {
                    if (!saved) return;
                    const nextRow = rows[rows.indexOf(row) + 1];
                    const nextTarget = nextRow?.querySelector(".key-number-input:not([readonly]), .key-hex-input:not([readonly])");
                    nextTarget?.focus();
                });
            }
        }));
        row.querySelector(".key-pair-save")?.addEventListener("click", () => saveRow(row));
        markDirty(row);
    });

    saveAllButton?.addEventListener("click", async () => {
        const readyRows = rows.filter((row) => {
            if (row.classList.contains("is-saved")) return false;
            return validNumber(row.querySelector(".key-number-input")?.value)
                && validHex(row.querySelector(".key-hex-input")?.value);
        });
        if (!readyRows.length) {
            showToast("Нет полностью заполненных строк", true);
            return;
        }
        saveAllButton.disabled = true;
        for (const row of readyRows) {
            await saveRow(row);
        }
        updateSummary();
    });

    finishButton?.addEventListener("click", (event) => {
        const hasDrafts = rows.some((row) => {
            if (row.classList.contains("is-saved")) return false;
            return Boolean(
                row.querySelector(".key-number-input")?.value.trim()
                || row.querySelector(".key-hex-input")?.value.trim()
            );
        });
        if (hasDrafts && !window.confirm("Есть несохранённые строки. Они останутся в черновике браузера. Завершить?")) {
            event.preventDefault();
        }
    });

    window.addEventListener("beforeunload", saveDrafts);
    updateSummary();
    const firstInput = rows[0]?.querySelector(".key-number-input:not([readonly]), .key-hex-input:not([readonly])");
    firstInput?.focus();
})();
