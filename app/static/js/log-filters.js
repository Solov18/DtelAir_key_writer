(() => {
    const form = document.getElementById("logFilterForm");
    const periodInput = document.getElementById("logPeriod");
    if (!form || !periodInput) return;

    const periodButtons = Array.from(form.querySelectorAll("[data-log-period]"));
    const dateInputs = Array.from(form.querySelectorAll("[data-log-custom-date]"));

    periodButtons.forEach((button) => {
        button.addEventListener("click", () => {
            periodInput.value = button.dataset.logPeriod || "all";
            dateInputs.forEach((input) => {
                input.value = "";
            });
            form.requestSubmit();
        });
    });

    dateInputs.forEach((input) => {
        input.addEventListener("change", () => {
            periodInput.value = "custom";
            periodButtons.forEach((button) => {
                button.classList.remove("is-active");
                button.setAttribute("aria-pressed", "false");
            });
        });
    });
})();
