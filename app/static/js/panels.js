document.addEventListener("DOMContentLoaded", () => {
    const searchInput = document.getElementById("panelSearch");
    const table = document.getElementById("panelsTable");
    const foundCounter = document.getElementById("panelsFound");
    const emptyMessage = document.getElementById("panelsSearchEmpty");

    if (!searchInput || !table || !foundCounter) {
        return;
    }

    const rows = Array.from(
        table.querySelectorAll("tbody tr[data-panel-row]")
    );

    function normalize(value) {
        return String(value || "")
            .toLowerCase()
            .replaceAll("ё", "е")
            .replace(/[^a-zа-я0-9]+/gi, "");
    }

    function filterPanels() {
        const query = normalize(searchInput.value);

        let visibleCount = 0;

        rows.forEach((row) => {
            const searchValue = normalize(
                row.dataset.search || row.textContent
            );

            const isVisible =
                query === "" ||
                searchValue.includes(query);

            row.hidden = !isVisible;

            if (isVisible) {
                visibleCount += 1;
            }
        });

        foundCounter.textContent = String(visibleCount);

        if (emptyMessage) {
            emptyMessage.hidden =
                visibleCount > 0 ||
                query === "";
        }
    }

    searchInput.addEventListener(
        "input",
        filterPanels
    );

    searchInput.addEventListener(
        "keydown",
        (event) => {
            if (event.key !== "Escape") {
                return;
            }

            searchInput.value = "";
            filterPanels();
            searchInput.blur();
        }
    );

    filterPanels();
});