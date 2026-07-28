(() => {
    const openModal = (modal) => {
        if (!modal) return;
        modal.classList.add("is-open");
        modal.setAttribute("aria-hidden", "false");
        document.body.classList.add("modal-open");
        window.setTimeout(() => {
            modal.querySelector("input:not([type='hidden']), select, textarea")?.focus();
        }, 30);
    };

    const closeModal = (modal) => {
        if (!modal) return;
        modal.classList.remove("is-open");
        modal.setAttribute("aria-hidden", "true");
        if (!document.querySelector(".uk-detail-modal.is-open")) {
            document.body.classList.remove("modal-open");
        }
    };

    document.querySelectorAll("[data-open-uk-detail-modal]").forEach((button) => {
        button.addEventListener("click", () => {
            openModal(document.getElementById(button.dataset.openUkDetailModal));
        });
    });

    document.querySelectorAll("[data-close-uk-detail-modal]").forEach((button) => {
        button.addEventListener("click", () => closeModal(button.closest(".uk-detail-modal")));
    });

    const search = document.getElementById("availablePanelSearch");
    const list = document.getElementById("availablePanelList");
    if (search && list) {
        search.addEventListener("input", () => {
            const normalize = window.smartSearchNormalize
                || ((value) => String(value || "").toLocaleLowerCase("ru-RU"));
            const query = normalize(search.value);
            list.querySelectorAll(".uk-selector-option").forEach((option) => {
                option.hidden = !normalize(option.innerText).includes(query);
            });
        });
    }

    document.querySelectorAll("[data-reveal-credentials]").forEach((button) => {
        let visible = false;
        button.addEventListener("click", async () => {
            const root = button.closest(".uk-modal-card, .uk-crm-access-card") || document;
            const output = root.querySelector("[data-credential-output]");
            const status = root.querySelector("[data-credential-status]");
            if (visible) {
                output?.setAttribute("hidden", "");
                if (output) {
                    output.querySelector("[data-credential-login-text]").textContent = "";
                    output.querySelector("[data-credential-password-text]").textContent = "";
                }
                button.textContent = button.closest(".uk-crm-access-card")
                    ? "Показать / скрыть"
                    : "Загрузить реквизиты";
                visible = false;
                return;
            }
            button.disabled = true;
            try {
                const response = await fetch(`/uk/${button.dataset.groupId}/credentials/reveal`, {
                    method: "POST",
                    headers: {"Accept": "application/json"},
                    cache: "no-store"
                });
                if (!response.ok) throw new Error("credentials");
                const data = await response.json();
                root.querySelector("[data-credential-login-text]").textContent = data.login || "Не указан";
                root.querySelector("[data-credential-password-text]").textContent = data.password || "Не указан";
                const loginInput = root.querySelector("[data-credential-login]");
                if (loginInput) loginInput.value = data.login || "";
                output?.removeAttribute("hidden");
                if (status) status.textContent = "Реквизиты открыты администратором.";
                button.textContent = "Скрыть реквизиты";
                visible = true;
            } catch {
                if (status) status.textContent = "Не удалось безопасно загрузить реквизиты.";
            } finally {
                button.disabled = false;
            }
        });
    });
})();
