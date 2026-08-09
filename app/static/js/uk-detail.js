(() => {
    const fetchSearchJson = (url) => window.SmartAutocomplete.fetchJson(url, {timeout: 10000});

    document.querySelectorAll("[data-uk-key-picker]").forEach((picker) => {
        const valueInput = picker.querySelector("[data-uk-key-value]");
        const trigger = picker.querySelector("[data-uk-key-trigger]");
        const label = picker.querySelector("[data-uk-key-label]");
        const dropdown = picker.querySelector("[data-uk-key-dropdown]");
        const search = picker.querySelector("[data-uk-key-search]");
        const type = picker.querySelector("[data-uk-key-type]");
        const results = picker.querySelector("[data-uk-key-results]");
        const empty = picker.querySelector("[data-uk-key-empty]");
        const findButton = picker.querySelector("[data-uk-key-find]");
        let items = [];
        let activeIndex = -1;
        let requestSequence = 0;
        let debounceTimer = null;

        const optionLabel = (item) => `${item.type} · №${item.number} · ${item.hex}`;
        const setActive = (index) => {
            const buttons = [...results.querySelectorAll('[role="option"]')];
            if (!buttons.length) {
                activeIndex = -1;
                return;
            }
            activeIndex = (index + buttons.length) % buttons.length;
            buttons.forEach((button, current) => button.classList.toggle("is-active", current === activeIndex));
            buttons[activeIndex].scrollIntoView({block: "nearest"});
        };
        const close = ({focus = false} = {}) => {
            dropdown.hidden = true;
            trigger.setAttribute("aria-expanded", "false");
            picker.classList.remove("is-open");
            if (focus) trigger.focus();
        };
        const choose = (item) => {
            valueInput.value = String(item.id);
            label.textContent = optionLabel(item);
            valueInput.dispatchEvent(new Event("change", {bubbles: true}));
            close({focus: true});
        };
        const render = () => {
            results.replaceChildren(...items.map((item, index) => {
                const button = document.createElement("button");
                button.type = "button";
                button.setAttribute("role", "option");
                button.dataset.index = String(index);
                button.innerHTML = `<span class="uk-key-picker__type"></span><b></b><code></code>`;
                button.querySelector(".uk-key-picker__type").textContent = item.type;
                button.querySelector("b").textContent = `№${item.number}`;
                button.querySelector("code").textContent = item.hex;
                button.style.setProperty("--key-type-color", item.color || "var(--accent)");
                button.addEventListener("pointerdown", (event) => event.preventDefault());
                button.addEventListener("click", () => choose(item));
                return button;
            }));
            empty.hidden = items.length !== 0;
            results.hidden = items.length === 0;
            setActive(items.length ? 0 : -1);
        };
        const load = async () => {
            const sequence = ++requestSequence;
            const params = new URLSearchParams({q: search.value.trim(), limit: "60"});
            if (type.value) params.set("key_type_id", type.value);
            picker.classList.add("is-loading");
            try {
                const payload = await fetchSearchJson(`${picker.dataset.source}?${params}`);
                if (sequence !== requestSequence) return;
                items = Array.isArray(payload.items) ? payload.items : [];
                render();
            } catch {
                if (sequence !== requestSequence) return;
                items = [];
                render();
                empty.textContent = "Не удалось загрузить свободные ключи";
                empty.hidden = false;
            } finally {
                if (sequence === requestSequence) picker.classList.remove("is-loading");
            }
        };
        const open = () => {
            dropdown.hidden = false;
            trigger.setAttribute("aria-expanded", "true");
            picker.classList.add("is-open");
            empty.textContent = "Свободные ключи не найдены";
            load();
            window.setTimeout(() => search.focus(), 0);
        };

        trigger.addEventListener("click", () => dropdown.hidden ? open() : close({focus: true}));
        search.addEventListener("input", () => {
            window.clearTimeout(debounceTimer);
            debounceTimer = window.setTimeout(load, 180);
        });
        findButton?.addEventListener("click", load);
        type.addEventListener("change", load);
        search.addEventListener("keydown", (event) => {
            if (event.key !== "Enter") return;
            event.preventDefault();
            event.stopPropagation();
            if (activeIndex >= 0 && items[activeIndex]) choose(items[activeIndex]);
            else load();
        });
        dropdown.addEventListener("keydown", (event) => {
            if (event.key === "Escape") {
                event.preventDefault();
                close({focus: true});
            } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                event.preventDefault();
                setActive(activeIndex + (event.key === "ArrowDown" ? 1 : -1));
            } else if (event.key === "Enter" && activeIndex >= 0) {
                event.preventDefault();
                choose(items[activeIndex]);
            }
        });
        document.addEventListener("pointerdown", (event) => {
            if (!dropdown.hidden && !picker.contains(event.target)) close();
        });
        picker.closest("form")?.addEventListener("submit", (event) => {
            if (valueInput.value) return;
            event.preventDefault();
            open();
            window.showAlert?.({title: "Выберите ключ", text: "Найдите и выберите свободный ключ с HEX."});
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
