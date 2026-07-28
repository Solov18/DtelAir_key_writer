(() => {
    const buttons = [...document.querySelectorAll("[data-user-filter]")];
    const cards = [...document.querySelectorAll("[data-user-card]")];
    const empty = document.querySelector("[data-users-filter-empty]");
    if (!buttons.length || !cards.length) return;

    const applyFilter = (filter, updateUrl = true) => {
        let visible = 0;
        cards.forEach((card) => {
            const matches = filter === "all"
                || (filter === "active" && card.dataset.active === "1")
                || card.dataset.role === filter;
            card.hidden = !matches;
            if (matches) visible += 1;
        });
        buttons.forEach((button) => {
            const selected = button.dataset.userFilter === filter;
            button.classList.toggle("is-active", selected);
            button.setAttribute("aria-pressed", String(selected));
        });
        if (empty) empty.hidden = visible > 0;
        if (updateUrl) {
            const url = new URL(window.location.href);
            if (filter === "all") url.searchParams.delete("filter");
            else url.searchParams.set("filter", filter);
            window.history.replaceState({}, "", url);
        }
    };

    buttons.forEach((button) => {
        button.addEventListener("click", () => applyFilter(button.dataset.userFilter));
    });

    const requested = new URL(window.location.href).searchParams.get("filter");
    const initial = buttons.some((button) => button.dataset.userFilter === requested) ? requested : "all";
    applyFilter(initial, false);
})();
