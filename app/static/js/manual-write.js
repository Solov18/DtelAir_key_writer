(() => {
    const checkboxes = Array.from(
        document.querySelectorAll('input[name="panel_ids"]')
    );
    const selectAll = document.getElementById("select-all-panels");
    const clearAll = document.getElementById("clear-all-panels");
    const count = document.getElementById("selectedPanelCount");
    const confirmation = document.getElementById("confirmManualWrite");
    const submit = document.getElementById("manualWriteButton");
    const hint = document.getElementById("manualSubmitHint");
    const form = document.getElementById("manualWriteForm");

    if (!form) {
        return;
    }

    function updateState() {
        const selected = checkboxes.filter((item) => item.checked).length;
        if (count) {
            count.textContent = String(selected);
        }
        const ready = selected > 0 && Boolean(confirmation?.checked);
        if (submit) {
            submit.disabled = !ready;
        }
        if (hint) {
            hint.textContent = selected === 0
                ? "Выберите хотя бы одну панель."
                : confirmation?.checked
                    ? "Можно запускать операцию."
                    : "Подтвердите проверку данных, чтобы продолжить.";
        }
    }

    checkboxes.forEach((item) => item.addEventListener("change", updateState));
    confirmation?.addEventListener("change", updateState);
    selectAll?.addEventListener("click", () => {
        checkboxes.forEach((item) => { item.checked = true; });
        updateState();
    });
    clearAll?.addEventListener("click", () => {
        checkboxes.forEach((item) => { item.checked = false; });
        updateState();
    });
    let writeInFlight = false;
    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const selected = checkboxes.filter((item) => item.checked).length;
        if (writeInFlight || !selected || !confirmation?.checked) {
            updateState();
            return;
        }
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
