(() => {
    const openModal = (modal) => {
        if (!modal) return;
        modal.classList.add("is-open");
        modal.setAttribute("aria-hidden", "false");
        document.body.classList.add("modal-open");
        const focusTarget = modal.querySelector("input:not([type='hidden']), select, textarea");
        window.setTimeout(() => focusTarget?.focus(), 30);
    };

    const closeModal = (modal) => {
        if (!modal) return;
        modal.classList.remove("is-open");
        modal.setAttribute("aria-hidden", "true");
        if (!document.querySelector(".uk-modal.is-open")) {
            document.body.classList.remove("modal-open");
        }
    };

    document.querySelectorAll("[data-open-uk-modal]").forEach((button) => {
        const selectedOnly = button.dataset.selectedOnly;
        if (selectedOnly && !button.closest("tr")?.classList.contains("is-selected")) {
            return;
        }
        button.addEventListener("click", () => {
            openModal(document.getElementById(button.dataset.openUkModal));
        });
    });

    document.querySelectorAll("[data-close-uk-modal]").forEach((button) => {
        button.addEventListener("click", () => closeModal(button.closest(".uk-modal")));
    });

    document.querySelectorAll(".uk-modal").forEach((modal) => {
        modal.addEventListener("click", (event) => {
            if (event.target === modal) closeModal(modal);
        });
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            closeModal(document.querySelector(".uk-modal.is-open"));
        }
    });

    document.querySelectorAll("[data-uk-row]").forEach((row) => {
        const navigate = () => {
            if (row.dataset.href) window.location.assign(row.dataset.href);
        };
        row.addEventListener("click", (event) => {
            if (event.target.closest("a, button, input, select, textarea, form")) return;
            navigate();
        });
        row.addEventListener("keydown", (event) => {
            if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                navigate();
            }
        });
    });

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
                button.textContent = "Показать логин и пароль";
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
