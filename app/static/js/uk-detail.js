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

    document.querySelectorAll(".uk-detail-modal").forEach((modal) => {
        modal.addEventListener("click", (event) => {
            if (event.target === modal) closeModal(modal);
        });
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            closeModal(document.querySelector(".uk-detail-modal.is-open"));
        }
    });

    document.querySelectorAll("form[data-confirm]").forEach((form) => {
        form.addEventListener("submit", (event) => {
            if (!window.confirm(form.dataset.confirm)) event.preventDefault();
        });
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
})();
