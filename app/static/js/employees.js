const selectAllBtn = document.getElementById("select-all-panels");
const clearAllBtn = document.getElementById("clear-all-panels");
const panelSearchInput = document.getElementById("employeePanelSearch");
const panelList = document.getElementById("employeePanelList");

const employeesSearch = document.getElementById("employeesSearch");
const employeesCards = document.getElementById("employeesCards");
const employeesFound = document.getElementById("employeesFound");

const employeeWriteSearch = document.getElementById("employeeWriteSearch");
const employeePicker = document.getElementById("employeePicker");

function getPanelCheckboxes() {
    return Array.from(document.querySelectorAll('input[name="panel_ids"]'));
}

function setPanelCheckboxes(value) {
    getPanelCheckboxes().forEach((checkbox) => {
        checkbox.checked = value;
    });
}

function filterItems(container, selector, query) {
    if (!container) {
        return 0;
    }

    let visible = 0;

    container.querySelectorAll(selector).forEach((item) => {
        const match = item.innerText.toLowerCase().includes(query);
        item.style.display = match ? "" : "none";

        if (match) {
            visible += 1;
        }
    });

    return visible;
}

function setEmployee(name) {
    if (employeeWriteSearch) {
        employeeWriteSearch.value = name;
    }

    if (employeePicker) {
        employeePicker.style.display = "none";
    }
}

if (selectAllBtn) {
    selectAllBtn.addEventListener("click", () => setPanelCheckboxes(true));
}

if (clearAllBtn) {
    clearAllBtn.addEventListener("click", () => setPanelCheckboxes(false));
}

if (panelSearchInput && panelList) {
    panelSearchInput.addEventListener("input", function () {
        filterItems(panelList, ".panel-option", this.value.toLowerCase().trim());
    });
}

if (employeesSearch && employeesCards && employeesFound) {
    employeesSearch.addEventListener("input", function () {
        const visible = filterItems(
            employeesCards,
            ".employee-card",
            this.value.toLowerCase().trim()
        );

        employeesFound.textContent = visible;
    });
}

document.querySelectorAll("[data-employee-select]").forEach((btn) => {
    btn.addEventListener("click", () => {
        setEmployee(btn.dataset.employeeSelect);
        window.scrollTo({ top: 0, behavior: "smooth" });
    });
});

if (employeeWriteSearch && employeePicker) {
    employeeWriteSearch.addEventListener("focus", () => {
        employeePicker.style.display = "grid";
    });

    employeeWriteSearch.addEventListener("input", function () {
        employeePicker.style.display = "grid";

        filterItems(
            employeePicker,
            ".employee-picker-item",
            this.value.toLowerCase().trim()
        );
    });

    employeePicker.querySelectorAll(".employee-picker-item").forEach((item) => {
        item.addEventListener("click", () => {
            setEmployee(item.dataset.name);
        });
    });

    document.addEventListener("click", (event) => {
        const clickedInside =
            employeePicker.contains(event.target) ||
            employeeWriteSearch.contains(event.target);

        if (!clickedInside) {
            employeePicker.style.display = "none";
        }
    });
}