(() => {
    document.querySelectorAll("[data-employee-choose-other]").forEach((button) => {
        button.addEventListener("click", () => {
            const input = document.querySelector("#issue-key input[name='key_value']");
            if (!input) return;
            input.value = "";
            input.focus();
            input.scrollIntoView({behavior: "smooth", block: "center"});
        });
    });
    const normalize = window.smartSearchNormalize || ((value) => (
        String(value || "")
            .normalize("NFKC")
            .toLocaleLowerCase("ru-RU")
            .replace(/ё/g, "е")
            .replace(/[^\p{L}\p{N}]+/gu, "")
    ));

    function openModal(modal) {
        if (!modal) {
            return;
        }
        if (window.AppModal) {
            window.AppModal.open(modal, document.activeElement);
            return;
        }

        modal.classList.add("is-open");
        modal.setAttribute("aria-hidden", "false");
        document.body.classList.add("employee-modal-open");

        const firstField = modal.querySelector("input, select, textarea");
        window.setTimeout(() => firstField?.focus(), 50);
    }

    document.querySelectorAll("[data-open-employee-modal]").forEach((trigger) => {
        trigger.addEventListener("click", (event) => {
            event.preventDefault();
            event.stopPropagation();

            const selectedOnly = trigger.dataset.selectedOnly;
            const selectedRow = document.querySelector(
                "[data-employee-row].is-selected"
            );

            if (
                selectedOnly &&
                !selectedRow?.dataset.href?.includes(
                    `selected_employee_id=${selectedOnly}`
                )
            ) {
                const targetRow = Array.from(
                    document.querySelectorAll("[data-employee-row]")
                ).find((row) => (
                    row.dataset.href?.includes(
                        `selected_employee_id=${selectedOnly}`
                    )
                ));

                if (targetRow?.dataset.href) {
                    const separator = targetRow.dataset.href.includes("?")
                        ? "&"
                        : "?";
                    window.location.assign(
                        `${targetRow.dataset.href}${separator}edit=1`
                    );
                }
                return;
            }

            openModal(
                document.getElementById(trigger.dataset.openEmployeeModal)
            );
        });
    });

    document.querySelectorAll("[data-employee-row]").forEach((row) => {
        const activate = () => {
            if (row.dataset.href) {
                window.location.assign(row.dataset.href);
            }
        };

        row.addEventListener("click", (event) => {
            if (event.target.closest("a, button, input, select, textarea, form")) {
                return;
            }
            activate();
        });

        row.addEventListener("keydown", (event) => {
            if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                activate();
            }
        });
    });

    const selectedRow = document.querySelector(
        "[data-employee-row].is-selected"
    );
    if (selectedRow) {
        selectedRow.scrollIntoView({ block: "nearest" });
    }

    const params = new URLSearchParams(window.location.search);
    if (params.get("edit") === "1") {
        openModal(document.getElementById("employeeEditModal"));
        params.delete("edit");
        const cleanQuery = params.toString();
        window.history.replaceState(
            {},
            "",
            `${window.location.pathname}${cleanQuery ? `?${cleanQuery}` : ""}`
        );
    }

    document.querySelectorAll("[data-local-smart-filter]").forEach((input) => {
        const selector = input.dataset.localSmartFilter;
        input.addEventListener("input", () => {
            const query = normalize(input.value);
            document.querySelectorAll(selector).forEach((item) => {
                const haystack = normalize(
                    item.dataset.search || item.textContent
                );
                item.hidden = Boolean(query) && !haystack.includes(query);
            });
        });
    });
})();
