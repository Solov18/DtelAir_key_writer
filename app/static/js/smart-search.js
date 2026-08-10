(() => {
    const normalize = (value) => {
        let normalized = String(value || "")
            .normalize("NFKC")
            .toLocaleLowerCase("ru-RU")
            .replace(/ё/g, "е")
            .replace(/[^\p{L}\p{N}]+/gu, "");
        if (/^8\d{10}$/.test(normalized)) {
            normalized = `7${normalized.slice(1)}`;
        }
        return normalized;
    };

    window.smartSearchNormalize = normalize;

    async function fetchJson(url, options = {}) {
        const controller = new AbortController();
        const timeoutMs = Number(options.timeout || 10000);
        const externalSignal = options.signal;
        const abortFromExternal = () => controller.abort(externalSignal?.reason);
        externalSignal?.addEventListener("abort", abortFromExternal, {once: true});
        const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
        try {
            const response = await fetch(url, {
                headers: {Accept: "application/json", ...(options.headers || {})},
                cache: options.cache || "no-store",
                signal: controller.signal,
                globalLoader: false,
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            return await response.json();
        } finally {
            window.clearTimeout(timeout);
            externalSignal?.removeEventListener("abort", abortFromExternal);
        }
    }

    const stateByInput = new WeakMap();

    function submitAfterSelection(input, item, source) {
        const detail = { input, item, source };
        const accepted = input.dispatchEvent(new CustomEvent(
            "smart-autocomplete:select",
            { bubbles: true, cancelable: true, detail }
        ));
        if (!accepted || input.dataset.smartSubmit === "false") return;

        const target = input.dataset.smartSubmit;
        const form = target && target !== "closest"
            ? document.getElementById(target)
            : input.closest("form");
        if (!form) return;

        window.setTimeout(() => {
            if (!form.isConnected) return;
            const submitter = form.querySelector('button[type="submit"], input[type="submit"]');
            form.requestSubmit(submitter || undefined);
        }, 0);
    }

    function closeSuggestions(input) {
        const state = stateByInput.get(input);
        if (!state) {
            return;
        }
        state.menu.hidden = true;
        state.activeIndex = -1;
        input.setAttribute("aria-expanded", "false");
        input.removeAttribute("aria-activedescendant");
    }

    function positionMenu(input, menu) {
        const rect = input.getBoundingClientRect();
        menu.style.left = `${Math.max(8, rect.left)}px`;
        menu.style.top = `${rect.bottom + 6}px`;
        menu.style.width = `${Math.max(280, rect.width)}px`;
        menu.style.maxWidth = `${Math.max(280, window.innerWidth - rect.left - 8)}px`;
    }

    function chooseSuggestion(input, item, source = "pointer") {
        const state = stateByInput.get(input);
        if (!state || !item || item.disabled) return;
        window.clearTimeout(state.timer);
        state.request?.abort();
        state.selecting = true;
        input.value = item.value;
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.dispatchEvent(new Event("change", { bubbles: true }));
        state.selecting = false;
        closeSuggestions(input);
        input.focus();
        submitAfterSelection(input, item, source);
    }

    function renderSuggestions(input, items) {
        const state = stateByInput.get(input);
        if (!state) {
            return;
        }

        state.items = items;
        state.activeIndex = -1;
        state.menu.replaceChildren();

        if (!items.length) {
            const empty = document.createElement("div");
            empty.className = "smart-search-empty";
            empty.setAttribute("role", "status");
            empty.textContent = "Ничего не найдено";
            state.menu.appendChild(empty);
            positionMenu(input, state.menu);
            state.menu.hidden = false;
            input.setAttribute("aria-expanded", "true");
            return;
        }

        items.forEach((item, index) => {
            const option = document.createElement("button");
            option.type = "button";
            option.className = "smart-search-option";
            option.setAttribute("role", "option");
            option.dataset.index = String(index);
            option.id = `${state.menu.id}-option-${index}`;
            option.disabled = Boolean(item.disabled);
            option.classList.toggle("is-disabled", Boolean(item.disabled));
            option.setAttribute("aria-disabled", item.disabled ? "true" : "false");

            const text = document.createElement("span");
            const label = document.createElement("b");
            label.textContent = item.label || item.value;
            text.appendChild(label);

            if (item.meta) {
                const meta = document.createElement("small");
                meta.textContent = item.meta;
                text.appendChild(meta);
            }

            const arrow = document.createElement("i");
            arrow.textContent = item.disabled ? "Недоступен" : "↵";
            option.append(text, arrow);

            option.addEventListener("pointerdown", (event) => {
                event.preventDefault();
                chooseSuggestion(input, item, event.pointerType === "touch" ? "touch" : "pointer");
            });
            state.menu.appendChild(option);
        });

        positionMenu(input, state.menu);
        state.menu.hidden = false;
        input.setAttribute("aria-expanded", "true");
    }

    function setActiveOption(input, nextIndex) {
        const state = stateByInput.get(input);
        if (!state?.items.length) {
            return;
        }

        let candidate = (nextIndex + state.items.length) % state.items.length;
        let attempts = 0;
        while (state.items[candidate]?.disabled && attempts < state.items.length) {
            candidate = (candidate + (nextIndex >= state.activeIndex ? 1 : -1) + state.items.length) % state.items.length;
            attempts += 1;
        }
        if (attempts >= state.items.length) return;
        state.activeIndex = candidate;

        state.menu.querySelectorAll(".smart-search-option").forEach(
            (option, index) => {
                option.classList.toggle(
                    "is-active",
                    index === state.activeIndex
                );
                option.setAttribute(
                    "aria-selected",
                    index === state.activeIndex ? "true" : "false"
                );
            }
        );
        const active = state.menu.querySelector(`.smart-search-option[data-index="${state.activeIndex}"]`);
        active?.scrollIntoView({ block: "nearest" });
        input.setAttribute("aria-activedescendant", active?.id || "");
    }

    function initialize(input) {
        if (!input || stateByInput.has(input)) return;
        const menu = document.createElement("div");
        menu.className = "smart-search-menu";
        menu.dataset.scope = input.dataset.smartSearch || "universal";
        menu.setAttribute("role", "listbox");
        menu.hidden = true;
        menu.id = `smart-search-${Math.random().toString(36).slice(2)}`;
        document.body.appendChild(menu);

        input.setAttribute("autocomplete", "off");
        input.setAttribute("aria-autocomplete", "list");
        input.setAttribute("aria-expanded", "false");
        input.setAttribute("aria-controls", menu.id);

        const state = {
            menu,
            items: [],
            activeIndex: -1,
            timer: 0,
            request: null,
            selecting: false,
        };
        stateByInput.set(input, state);

        const buildRequest = (query) => {
            const params = new URLSearchParams({
                q: query,
                limit: input.dataset.smartSearchLimit || "8",
            });
            if (!input.dataset.smartSearchUrl) {
                params.set("scope", input.dataset.smartSearch || "universal");
            }
            const mappings = (input.dataset.smartSearchParams || "")
                .split(",")
                .map((value) => value.trim())
                .filter(Boolean);
            mappings.forEach((mapping) => {
                const [selector, parameter] = mapping.split(":");
                const value = document.querySelector(selector)?.value;
                if (parameter && value) params.set(parameter, value);
            });
            return {
                url: `${input.dataset.smartSearchUrl || "/api/search/suggestions"}?${params}`,
                params,
            };
        };

        const runSearch = async (immediate = false) => {
            window.clearTimeout(state.timer);
            state.request?.abort();
            const query = input.value.trim();
            const minimum = Number(input.dataset.smartSearchMinLength || 2);
            if (normalize(query).length < minimum) {
                closeSuggestions(input);
                input.dispatchEvent(new CustomEvent("smart-autocomplete:idle", {bubbles: true}));
                return;
            }
            const execute = async () => {
                state.request = new AbortController();
                const request = buildRequest(query);
                input.dispatchEvent(new CustomEvent("smart-autocomplete:loading", {bubbles: true}));
                try {
                    const payload = await fetchJson(request.url, {signal: state.request.signal});
                    const items = Array.isArray(payload.items) ? payload.items : [];
                    renderSuggestions(input, items);
                    input.dispatchEvent(new CustomEvent("smart-autocomplete:loaded", {
                        bubbles: true,
                        detail: {items},
                    }));
                } catch (error) {
                    if (error.name !== "AbortError") {
                        closeSuggestions(input);
                        input.dispatchEvent(new CustomEvent("smart-autocomplete:error", {bubbles: true}));
                    }
                }
            };
            if (immediate) await execute();
            else state.timer = window.setTimeout(execute, 180);
        };

        input.addEventListener("input", () => {
            if (state.selecting) return;
            runSearch(false);
        });

        input.addEventListener("keydown", (event) => {
            if (event.key === "ArrowDown") {
                if (state.menu.hidden || !state.items.length) return;
                event.preventDefault();
                setActiveOption(input, state.activeIndex + 1);
            } else if (event.key === "ArrowUp") {
                if (state.menu.hidden || !state.items.length) return;
                event.preventDefault();
                setActiveOption(input, state.activeIndex - 1);
            } else if (event.key === "Enter") {
                event.preventDefault();
                const exact = state.items.find((item) => normalize(item.value) === normalize(input.value));
                const selected = state.activeIndex >= 0
                    ? state.items[state.activeIndex]
                    : exact || (!state.menu.hidden ? state.items[0] : null);
                if (selected) chooseSuggestion(input, selected, "keyboard");
                else runSearch(true);
            } else if (event.key === "Escape") {
                event.preventDefault();
                closeSuggestions(input);
            }
        });

        state.runSearch = runSearch;

        input.addEventListener("focus", () => {
            if (state.items.length && normalize(input.value).length >= 2) {
                positionMenu(input, menu);
                menu.hidden = false;
                input.setAttribute("aria-expanded", "true");
            }
        });

        input.addEventListener("blur", () => {
            window.setTimeout(() => closeSuggestions(input), 100);
        });
    }

    document.querySelectorAll("input[data-smart-search]").forEach(initialize);

    window.SmartAutocomplete = {
        enhance: initialize,
        close: closeSuggestions,
        search(input) {
            const state = stateByInput.get(input);
            return state?.runSearch?.(true);
        },
        normalize,
        fetchJson,
    };

    const repositionOpenMenus = () => {
        document.querySelectorAll("input[data-smart-search]").forEach((input) => {
            const state = stateByInput.get(input);
            if (state && !state.menu.hidden) {
                positionMenu(input, state.menu);
            }
        });
    };

    window.addEventListener("resize", repositionOpenMenus);
    window.addEventListener("scroll", repositionOpenMenus, true);
})();
