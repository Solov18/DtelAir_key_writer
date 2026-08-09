(() => {
    const OPEN_SELECTOR = "[data-modal-open], [data-open-uk-modal], [data-open-uk-detail-modal], [data-keys-modal], [data-open-modal], [data-open-employee-modal]";
    const CLOSE_SELECTOR = "[data-modal-close], [data-close-uk-modal], [data-close-uk-detail-modal], [data-close], [data-close-modal], [data-close-employee-modal]";
    const MODAL_SELECTOR = ".app-modal, .uk-modal, .uk-detail-modal, .keys-modal, .employee-modal, .panels-modal, .modal-backdrop";
    const OPEN_MODAL_SELECTOR = MODAL_SELECTOR.split(",").flatMap((selector) => [
        `${selector.trim()}.is-open`, `${selector.trim()}.active`, `${selector.trim()}:not([hidden])[aria-hidden='false']`
    ]).join(",");
    let activeModal = null;
    let returnFocus = null;

    const surfaceFor = (modal) => modal?.querySelector(
        ".app-modal-surface, .uk-modal-card, .keys-modal-window, .employee-modal-card, .modal-card"
    );

    const formSnapshot = (modal) => [...modal.querySelectorAll("form")].map(
        (form) => new URLSearchParams(new FormData(form)).toString()
    );

    const markClean = (modal) => {
        modal.__appModalSnapshot = formSnapshot(modal);
    };

    const isDirty = (modal) => {
        const before = modal.__appModalSnapshot || [];
        const after = formSnapshot(modal);
        return before.length !== after.length || after.some((value, index) => value !== before[index]);
    };

    const resolveModal = (value) => {
        if (!value) return null;
        if (value instanceof Element) return value.matches(MODAL_SELECTOR) ? value : value.closest(MODAL_SELECTOR);
        return document.getElementById(String(value));
    };

    const open = (value, source = document.activeElement) => {
        const modal = resolveModal(value);
        if (!modal) return;
        activeModal = modal;
        returnFocus = source;
        surfaceFor(modal)?.classList.add("app-modal-surface", "custom-scroll");
        modal.hidden = false;
        modal.classList.add("is-open", "active");
        modal.setAttribute("aria-hidden", "false");
        document.body.classList.add("modal-open", "app-modal-open");
        markClean(modal);
        window.setTimeout(() => {
            const field = modal.querySelector("input:not([type='hidden']):not([disabled]), textarea:not([disabled]), .app-combobox__trigger, button");
            field?.focus?.();
        }, 30);
    };

    const closeNow = (modal) => {
        modal.classList.remove("is-open", "active");
        modal.setAttribute("aria-hidden", "true");
        if (modal.classList.contains("panels-modal")) modal.hidden = true;
        if (!document.querySelector(OPEN_MODAL_SELECTOR)) {
            document.body.classList.remove("modal-open", "app-modal-open");
        }
        activeModal = null;
        window.setTimeout(() => returnFocus?.focus?.(), 0);
    };

    const close = async (value, {force = false} = {}) => {
        const modal = resolveModal(value) || activeModal;
        if (!modal) return false;
        if (!force && isDirty(modal) && window.showConfirm) {
            const accepted = await window.showConfirm({
                title: "Закрыть без сохранения?",
                message: "Введённые изменения не сохранены.",
                confirmText: "Закрыть",
                cancelText: "Продолжить редактирование",
            });
            if (!accepted) return false;
        }
        closeNow(modal);
        return true;
    };

    document.addEventListener("click", (event) => {
        const opener = event.target.closest?.(OPEN_SELECTOR);
        if (opener) {
            if (opener.dataset.selectedOnly) return;
            const id = opener.dataset.modalOpen || opener.dataset.openUkModal
                || opener.dataset.openUkDetailModal || opener.dataset.keysModal
                || opener.dataset.openModal || opener.dataset.openEmployeeModal;
            if (id) {
                event.preventDefault();
                open(id, opener);
            }
            return;
        }
        const closer = event.target.closest?.(CLOSE_SELECTOR);
        if (closer) {
            event.preventDefault();
            event.stopImmediatePropagation();
            close(closer.dataset.close ? document.getElementById(closer.dataset.close) : closer.closest(MODAL_SELECTOR));
            return;
        }
        const modal = event.target.closest?.(MODAL_SELECTOR);
        if (modal && event.target === modal) {
            event.preventDefault();
            event.stopImmediatePropagation();
        }
    }, true);

    document.addEventListener("keydown", (event) => {
        const modal = document.querySelector(OPEN_MODAL_SELECTOR);
        if (!modal) return;
        if (event.key === "Escape") {
            event.preventDefault();
            event.stopImmediatePropagation();
            return;
        }
        if (event.key === "Tab") {
            const surface = surfaceFor(modal) || modal;
            const focusable = [...surface.querySelectorAll(
                "button:not([disabled]), input:not([disabled]):not([type='hidden']), select:not([disabled]), textarea:not([disabled]), a[href], [tabindex]:not([tabindex='-1'])"
            )].filter((element) => !element.hidden && element.getClientRects().length);
            if (!focusable.length) return;
            const first = focusable[0];
            const last = focusable.at(-1);
            if (event.shiftKey && document.activeElement === first) {
                event.preventDefault();
                last.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault();
                first.focus();
            }
        }
    }, true);

    document.addEventListener("submit", (event) => {
        const modal = event.target.closest?.(MODAL_SELECTOR);
        if (modal) markClean(modal);
    }, true);

    document.addEventListener("DOMContentLoaded", () => {
        document.querySelectorAll(MODAL_SELECTOR).forEach((modal) => {
            surfaceFor(modal)?.classList.add("app-modal-surface", "custom-scroll");
            modal.setAttribute("data-explicit-close", "true");
        });
    });

    window.AppModal = {open, close, markClean};
})();
