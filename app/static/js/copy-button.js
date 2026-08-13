(function () {
    "use strict";

    const resetTimers = new WeakMap();

    async function writeClipboard(value) {
        if (navigator.clipboard && window.isSecureContext) {
            await navigator.clipboard.writeText(value);
            return;
        }

        const helper = document.createElement("textarea");
        helper.value = value;
        helper.setAttribute("readonly", "");
        helper.style.position = "fixed";
        helper.style.opacity = "0";
        helper.style.pointerEvents = "none";
        document.body.appendChild(helper);
        helper.select();
        const copied = document.execCommand("copy");
        helper.remove();
        if (!copied) throw new Error("Clipboard copy failed");
    }

    function resetButton(button) {
        button.classList.remove("is-copied", "is-copy-error");
        const label = button.dataset.copyLabel || "Копировать";
        button.title = label;
        button.setAttribute("aria-label", label);
        resetTimers.delete(button);
    }

    async function copyValue(button) {
        const value = button.dataset.copyValue || "";
        if (!value) return;

        const previousTimer = resetTimers.get(button);
        if (previousTimer) window.clearTimeout(previousTimer);

        try {
            await writeClipboard(value);
            button.classList.remove("is-copy-error");
            button.classList.add("is-copied");
            button.title = "Скопировано";
            button.setAttribute("aria-label", "Скопировано");
        } catch (error) {
            button.classList.remove("is-copied");
            button.classList.add("is-copy-error");
            button.title = "Не удалось скопировать";
            button.setAttribute("aria-label", "Не удалось скопировать");
        }

        resetTimers.set(button, window.setTimeout(() => resetButton(button), 1400));
    }

    document.addEventListener("click", (event) => {
        const button = event.target.closest(".copy-button[data-copy-value]");
        if (!button) return;
        event.preventDefault();
        event.stopPropagation();
        copyValue(button);
    });
})();
