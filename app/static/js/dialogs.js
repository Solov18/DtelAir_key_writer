(() => {
    const root = document.getElementById("appDialog");
    if (!root) return;

    const panel = root.querySelector(".app-dialog__panel");
    const eyebrow = root.querySelector("[data-dialog-eyebrow]");
    const title = root.querySelector("[data-dialog-title]");
    const message = root.querySelector("[data-dialog-message]");
    const confirmButton = root.querySelector("[data-dialog-confirm]");
    const cancelButton = root.querySelector("[data-dialog-cancel]");
    const closeButton = root.querySelector("[data-dialog-close]");
    let resolver = null;
    let sourceElement = null;
    let dangerMode = false;

    const focusable = () => [...panel.querySelectorAll(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    )].filter((element) => !element.hidden);

    const finish = (accepted) => {
        if (!root.classList.contains("is-open")) return;
        root.classList.remove("is-open");
        document.body.classList.remove("dialog-open");
        root.setAttribute("aria-hidden", "true");
        const resolve = resolver;
        resolver = null;
        window.setTimeout(() => {
            sourceElement?.focus?.();
            sourceElement = null;
        }, 0);
        resolve?.(accepted);
    };

    const show = ({
        type = "confirm",
        title: heading = "Подтвердите действие",
        message: body = "",
        confirmText = "Продолжить",
        cancelText = "Отмена",
        source = document.activeElement,
    } = {}) => {
        if (resolver) finish(false);
        dangerMode = type === "danger";
        sourceElement = source;
        root.dataset.variant = dangerMode ? "danger" : (type === "info" ? "info" : "confirm");
        eyebrow.textContent = dangerMode ? "Опасное действие" : (type === "info" ? "Сообщение" : "Подтверждение");
        title.textContent = heading;
        message.textContent = body;
        confirmButton.textContent = confirmText;
        cancelButton.textContent = cancelText;
        cancelButton.hidden = type === "info";
        closeButton.hidden = dangerMode;
        root.classList.add("is-open");
        root.setAttribute("aria-hidden", "false");
        document.body.classList.add("dialog-open");
        window.setTimeout(() => (type === "info" ? confirmButton : cancelButton).focus(), 20);
        return new Promise((resolve) => {
            resolver = resolve;
        });
    };

    confirmButton.addEventListener("click", () => finish(true));
    cancelButton.addEventListener("click", () => finish(false));
    closeButton.addEventListener("click", () => finish(false));
    root.addEventListener("mousedown", (event) => {
        if (event.target === root && !dangerMode) finish(false);
    });
    document.addEventListener("keydown", (event) => {
        if (!root.classList.contains("is-open")) return;
        if (event.key === "Escape") {
            event.preventDefault();
            finish(false);
            return;
        }
        if (event.key === "Enter" && !event.target.closest("textarea") && event.target !== cancelButton) {
            event.preventDefault();
            finish(true);
            return;
        }
        if (event.key !== "Tab") return;
        const items = focusable();
        if (!items.length) return;
        const first = items[0];
        const last = items[items.length - 1];
        if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
        }
    });

    window.showAlert = (options = {}) => show({...options, type: "info"});
    window.showConfirm = (options = {}) => show({...options, type: "confirm"});
    window.showDangerConfirm = (options = {}) => show({...options, type: "danger"});

    const approvedForms = new WeakSet();
    document.addEventListener("submit", async (event) => {
        const form = event.target.closest?.("form");
        const submitter = event.submitter;
        const promptSource = submitter?.dataset.confirm ? submitter : form;
        if (!form || !promptSource?.dataset.confirm || approvedForms.has(form)) {
            if (form) approvedForms.delete(form);
            return;
        }
        event.preventDefault();
        const isDanger = promptSource.dataset.confirmVariant === "danger"
            || form.dataset.confirmVariant === "danger"
            || Boolean(submitter?.matches(".danger-btn, .is-danger"))
            || Boolean(form.querySelector(".danger-btn, .is-danger"));
        const confirmText = promptSource.dataset.confirmAction
            || submitter?.textContent?.trim()
            || "Продолжить";
        const accepted = await (isDanger ? window.showDangerConfirm : window.showConfirm)({
            title: promptSource.dataset.confirmTitle || form.dataset.confirmTitle || (isDanger ? "Подтвердите опасное действие" : "Подтвердите действие"),
            message: promptSource.dataset.confirm,
            confirmText,
            cancelText: promptSource.dataset.confirmCancel || form.dataset.confirmCancel || "Отмена",
            source: submitter || form,
        });
        if (!accepted) return;
        approvedForms.add(form);
        form.requestSubmit(submitter || undefined);
    }, true);
})();
