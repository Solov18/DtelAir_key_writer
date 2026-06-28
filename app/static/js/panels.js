document.addEventListener("DOMContentLoaded", function () {
    const searchInput = document.getElementById("panelSearch");
    const table = document.getElementById("panelsTable");
    const foundCounter = document.getElementById("panelsFound");

    if (!searchInput || !table || !foundCounter) {
        return;
    }

    const rows = Array.from(table.querySelectorAll("tbody tr"));

    function filterPanels() {
        const query = searchInput.value.trim().toLowerCase();
        let visibleCount = 0;

        rows.forEach((row) => {
            const text = row.innerText.toLowerCase();
            const isVisible = text.includes(query);

            row.style.display = isVisible ? "" : "none";

            if (isVisible) {
                visibleCount += 1;
            }
        });

        foundCounter.textContent = visibleCount;
    }

    searchInput.addEventListener("input", filterPanels);
});