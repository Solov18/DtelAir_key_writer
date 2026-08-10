(() => {
    const fetchSearchJson = (url) => window.SmartAutocomplete.fetchJson(url, {timeout: 10000});

    document.querySelectorAll("[data-uk-key-selection]").forEach((picker) => {
        const form = picker.closest("form");
        const valueInput = picker.querySelector("[data-uk-key-value]");
        const searchInput = picker.querySelector("input[data-smart-search]");
        const typeFilter = picker.querySelector("select");
        const findButton = picker.querySelector("[data-uk-key-find]");
        const status = picker.querySelector("[data-uk-key-search-status]");
        const selectedCard = picker.querySelector("[data-uk-key-selected]");
        const selectedTitle = picker.querySelector("[data-uk-key-title]");
        const selectedHex = picker.querySelector("[data-uk-key-hex]");
        const selectedStatus = picker.querySelector("[data-uk-key-status]");
        const selectedColor = picker.querySelector("[data-uk-key-color]");
        const clearButton = picker.querySelector("[data-uk-key-clear]");
        let selectedItem = null;

        const clearSelection = ({clearSearch = false} = {}) => {
            selectedItem = null;
            valueInput.value = "";
            selectedCard.hidden = true;
            if (clearSearch) searchInput.value = "";
        };

        const choose = (item) => {
            if (!item?.available) return;
            selectedItem = item;
            valueInput.value = String(item.id);
            selectedTitle.textContent = `${item.type} · №${item.number}`;
            selectedHex.textContent = item.hex;
            selectedStatus.textContent = item.status_name || "Свободен";
            selectedColor.style.setProperty("--key-type-color", item.color || "var(--accent)");
            selectedCard.hidden = false;
            status.textContent = "Ключ выбран. Можно выбрать панели и продолжить выдачу.";
        };

        searchInput.addEventListener("smart-autocomplete:select", (event) => {
            event.preventDefault();
            choose(event.detail.item);
        });
        searchInput.addEventListener("smart-autocomplete:loading", () => {
            status.textContent = "Поиск…";
        });
        searchInput.addEventListener("smart-autocomplete:loaded", (event) => {
            const items = event.detail.items || [];
            if (!items.length) status.textContent = "Ключи не найдены";
            else if (!items.some((item) => item.available)) {
                status.textContent = "Найдены только уже используемые ключи. Выберите свободный ключ.";
            } else {
                status.textContent = `Найдено вариантов: ${items.length}. Выберите свободный ключ.`;
            }
        });
        searchInput.addEventListener("smart-autocomplete:error", () => {
            status.textContent = "Не удалось выполнить поиск. Попробуйте ещё раз.";
        });
        searchInput.addEventListener("input", () => {
            if (selectedItem && searchInput.value !== selectedItem.value) clearSelection();
        });
        typeFilter.addEventListener("change", () => {
            clearSelection();
            if (searchInput.value.trim()) window.SmartAutocomplete.search(searchInput);
        });
        findButton.addEventListener("click", () => window.SmartAutocomplete.search(searchInput));
        clearButton.addEventListener("click", () => {
            clearSelection({clearSearch: true});
            status.textContent = "Введите номер, HEX или название типа ключа.";
            searchInput.focus();
        });
        form?.addEventListener("submit", (event) => {
            if (valueInput.value) return;
            event.preventDefault();
            status.textContent = "Сначала найдите и выберите свободный ключ с HEX.";
            searchInput.focus();
            window.showAlert?.({
                title: "Выберите ключ",
                text: "Введите номер или HEX и выберите свободный ключ из найденных вариантов.",
            });
        });
    });

    document.querySelectorAll("[data-uk-issue-panels]").forEach((picker) => {
        const searchInput = picker.querySelector("[data-uk-panels-search]");
        const findButton = picker.querySelector("[data-uk-panels-find]");
        const list = picker.querySelector("[data-uk-panels-list]");
        const empty = picker.querySelector("[data-uk-panels-empty]");
        const count = picker.querySelector("[data-uk-panels-count]");
        const selectedText = picker.querySelector("[data-uk-panels-selected]");
        const selected = new Map();
        let items = [];
        let requestSequence = 0;
        let debounceTimer = 0;

        const updateSummary = () => {
            const values = [...selected.values()];
            count.textContent = String(values.length);
            const names = values.slice(0, 3).map((item) => `${item.address} — ${item.point}`);
            selectedText.textContent = values.length
                ? `${names.join("; ")}${values.length > 3 ? ` и ещё ${values.length - 3}` : ""}`
                : "Панели пока не выбраны";
        };
        const render = () => {
            list.replaceChildren(...items.map((item) => {
                const option = document.createElement("label");
                option.className = "uk-issue-panel-option";
                const input = document.createElement("input");
                input.type = "checkbox";
                input.name = "panel_link_ids";
                input.value = String(item.link_id);
                input.checked = selected.has(String(item.link_id));
                const body = document.createElement("span");
                const address = document.createElement("b");
                address.textContent = item.address;
                const details = document.createElement("small");
                details.textContent = `${item.point} · ${item.mac}`;
                body.append(address, details);
                input.addEventListener("change", () => {
                    if (input.checked) selected.set(String(item.link_id), item);
                    else selected.delete(String(item.link_id));
                    updateSummary();
                });
                option.append(input, body);
                return option;
            }));
            empty.hidden = items.length !== 0;
            list.hidden = items.length === 0;
        };
        const load = async () => {
            const sequence = ++requestSequence;
            const params = new URLSearchParams({q: searchInput.value.trim(), limit: "100"});
            picker.classList.add("is-loading");
            empty.textContent = "Поиск панелей…";
            empty.hidden = false;
            try {
                const payload = await fetchSearchJson(`${picker.dataset.source}?${params}`);
                if (sequence !== requestSequence) return;
                items = Array.isArray(payload.items) ? payload.items : [];
                empty.textContent = "Панели не найдены";
                render();
            } catch (error) {
                if (sequence !== requestSequence) return;
                items = [];
                render();
                empty.textContent = error?.name === "AbortError"
                    ? "Поиск панелей превысил время ожидания"
                    : "Не удалось выполнить поиск панелей";
                empty.hidden = false;
            } finally {
                if (sequence === requestSequence) picker.classList.remove("is-loading");
            }
        };

        searchInput.addEventListener("input", () => {
            window.clearTimeout(debounceTimer);
            debounceTimer = window.setTimeout(load, 220);
        });
        searchInput.addEventListener("keydown", (event) => {
            if (event.key !== "Enter") return;
            event.preventDefault();
            event.stopPropagation();
            load();
        });
        findButton?.addEventListener("click", load);
        picker.querySelector("[data-uk-panels-select-all]").addEventListener("click", () => {
            items.forEach((item) => selected.set(String(item.link_id), item));
            render();
            updateSummary();
        });
        picker.querySelector("[data-uk-panels-clear]").addEventListener("click", () => {
            selected.clear();
            render();
            updateSummary();
        });
        picker.closest("form").addEventListener("submit", (event) => {
            if (selected.size) {
                list.querySelectorAll("input").forEach((input) => input.remove());
                selected.forEach((item) => {
                    const input = document.createElement("input");
                    input.type = "hidden";
                    input.name = "panel_link_ids";
                    input.value = String(item.link_id);
                    list.append(input);
                });
                return;
            }
            event.preventDefault();
            searchInput.focus();
            window.showAlert?.({title: "Выберите панели", text: "Отметьте хотя бы одну панель для записи ключа."});
        });
        updateSummary();
        load();
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
