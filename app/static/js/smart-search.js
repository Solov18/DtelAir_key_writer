(() => {
    "use strict";

    const normalize = (value) => {
        let normalized = String(value || "")
            .normalize("NFKC")
            .toLocaleLowerCase("ru-RU")
            .replace(/ё/g, "е")
            .replace(/[^\p{L}\p{N}]+/gu, "");
        if (/^8\d{10}$/.test(normalized)) normalized = `7${normalized.slice(1)}`;
        return normalized;
    };

    window.smartSearchNormalize = normalize;

    async function fetchJson(url, options = {}) {
        const controller = new AbortController();
        const timeoutMs = Number(options.timeout || 10000);
        const externalSignal = options.signal;
        let abortReason = "";
        const abortFromExternal = () => {
            abortReason = "external";
            controller.abort(externalSignal?.reason);
        };
        externalSignal?.addEventListener("abort", abortFromExternal, {once: true});
        const timeout = window.setTimeout(() => {
            abortReason = "timeout";
            controller.abort();
        }, timeoutMs);
        try {
            const response = await fetch(url, {
                headers: {Accept: "application/json", ...(options.headers || {})},
                cache: options.cache || "no-store",
                signal: controller.signal,
                globalLoader: false,
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            return await response.json();
        } catch (error) {
            if (error?.name === "AbortError") error.smartSearchReason = abortReason || "aborted";
            throw error;
        } finally {
            window.clearTimeout(timeout);
            externalSignal?.removeEventListener("abort", abortFromExternal);
        }
    }

    const stateByInput = new WeakMap();
    const DEFAULTS = {
        debounceMs: 180,
        timeoutMs: 10000,
        minimumQueryLength: 2,
        limit: 8,
        queryParameter: "q",
        explicitSearch: true,
        renderMenu: true,
        autoSearch: true,
    };

    function emit(input, name, detail) {
        return input.dispatchEvent(new CustomEvent(name, {
            bubbles: true,
            cancelable: name === "smart-autocomplete:select",
            detail,
        }));
    }

    function closeSuggestions(input) {
        const state = stateByInput.get(input);
        if (!state) return;
        state.menu.hidden = true;
        state.activeIndex = -1;
        input.setAttribute("aria-expanded", "false");
        input.removeAttribute("aria-activedescendant");
        state.options.onClose?.();
    }

    function positionMenu(input, menu) {
        const rect = input.getBoundingClientRect();
        menu.style.left = `${Math.max(8, rect.left)}px`;
        menu.style.top = `${rect.bottom + 6}px`;
        menu.style.width = `${Math.max(280, rect.width)}px`;
        menu.style.maxWidth = `${Math.max(280, window.innerWidth - rect.left - 8)}px`;
    }

    function renderState(input, text, className) {
        const state = stateByInput.get(input);
        if (!state?.options.renderMenu) return;
        const message = document.createElement("div");
        message.className = className;
        message.setAttribute("role", "status");
        message.textContent = text;
        state.menu.replaceChildren(message);
        positionMenu(input, state.menu);
        state.menu.hidden = false;
        input.setAttribute("aria-expanded", "true");
    }

    function submitAfterSelection(input, item, source, callbackAccepted) {
        const accepted = emit(input, "smart-autocomplete:select", {input, item, source});
        if (!accepted || callbackAccepted === false || input.dataset.smartSubmit === "false") return;
        const target = input.dataset.smartSubmit;
        const form = target && target !== "closest" ? document.getElementById(target) : input.closest("form");
        if (!form) return;
        window.setTimeout(() => {
            if (!form.isConnected) return;
            const submitter = form.querySelector('button[type="submit"], input[type="submit"]');
            form.requestSubmit(submitter || undefined);
        }, 0);
    }

    function chooseSuggestion(input, item, source = "pointer") {
        const state = stateByInput.get(input);
        if (!state || !item || item.disabled) return;
        window.clearTimeout(state.timer);
        state.request?.abort("selected");
        state.selecting = true;
        input.value = item.value;
        input.dispatchEvent(new Event("input", {bubbles: true}));
        input.dispatchEvent(new Event("change", {bubbles: true}));
        state.selecting = false;
        closeSuggestions(input);
        input.focus();
        const accepted = state.options.onSelect?.(item, {input, source});
        submitAfterSelection(input, item, source, accepted);
    }

    function renderSuggestions(input, items) {
        const state = stateByInput.get(input);
        if (!state) return;
        state.items = items;
        state.activeIndex = -1;
        state.menu.replaceChildren();

        state.options.onResults?.(items, {input, query: state.lastQuery});
        if (!state.options.renderMenu) {
            closeSuggestions(input);
            return;
        }

        if (!items.length) {
            const empty = document.createElement("div");
            empty.className = "smart-search-empty";
            empty.setAttribute("role", "status");
            empty.textContent = state.options.emptyText || "Ничего не найдено";
            state.menu.appendChild(empty);
        } else {
            items.forEach((item, index) => {
                const custom = state.options.renderer?.(item, {input, index});
                const option = custom instanceof HTMLElement ? custom : document.createElement("button");
                if (!(custom instanceof HTMLElement)) {
                    option.type = "button";
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
                }
                option.classList.add("smart-search-option");
                option.setAttribute("role", "option");
                option.dataset.index = String(index);
                option.id = `${state.menu.id}-option-${index}`;
                option.disabled = Boolean(item.disabled);
                option.classList.toggle("is-disabled", Boolean(item.disabled));
                option.setAttribute("aria-disabled", item.disabled ? "true" : "false");
                option.addEventListener("pointerdown", (event) => {
                    event.preventDefault();
                    chooseSuggestion(input, item, event.pointerType === "touch" ? "touch" : "pointer");
                });
                state.menu.appendChild(option);
            });
        }
        positionMenu(input, state.menu);
        state.menu.hidden = false;
        input.setAttribute("aria-expanded", "true");
    }

    function setActiveOption(input, nextIndex) {
        const state = stateByInput.get(input);
        if (!state?.items.length) return;
        const direction = nextIndex >= state.activeIndex ? 1 : -1;
        let candidate = (nextIndex + state.items.length) % state.items.length;
        let attempts = 0;
        while (state.items[candidate]?.disabled && attempts < state.items.length) {
            candidate = (candidate + direction + state.items.length) % state.items.length;
            attempts += 1;
        }
        if (attempts >= state.items.length) return;
        state.activeIndex = candidate;
        state.menu.querySelectorAll(".smart-search-option").forEach((option, index) => {
            const active = index === candidate;
            option.classList.toggle("is-active", active);
            option.setAttribute("aria-selected", active ? "true" : "false");
        });
        const active = state.menu.querySelector(`.smart-search-option[data-index="${candidate}"]`);
        active?.scrollIntoView({block: "nearest"});
        input.setAttribute("aria-activedescendant", active?.id || "");
    }

    function readMappedParams(input) {
        const params = {};
        (input.dataset.smartSearchParams || "").split(",").map((value) => value.trim()).filter(Boolean)
            .forEach((mapping) => {
                const [selector, parameter] = mapping.split(":");
                const value = document.querySelector(selector)?.value;
                if (parameter && value) params[parameter] = value;
            });
        return params;
    }

    function buildRequest(input, query, state) {
        if (state.options.buildUrl) return state.options.buildUrl(query, {input});
        const params = new URLSearchParams({
            [state.options.queryParameter]: query,
            limit: String(state.options.limit),
        });
        const extra = state.options.getParams?.({input, query}) || {};
        const entries = extra instanceof URLSearchParams ? extra.entries() : Object.entries(extra);
        for (const [key, value] of entries) if (value !== "" && value != null) params.set(key, value);
        Object.entries(readMappedParams(input)).forEach(([key, value]) => params.set(key, value));
        const endpoint = state.options.endpoint || input.dataset.smartSearchUrl || "/api/search/suggestions";
        if (!state.options.endpoint && !input.dataset.smartSearchUrl) {
            params.set("scope", input.dataset.smartSearch || "universal");
        }
        return `${endpoint}${endpoint.includes("?") ? "&" : "?"}${params}`;
    }

    function bindSearchButton(state) {
        const button = state.options.searchButton;
        if (state.searchButton === button) return;
        if (state.searchButton) state.searchButton.removeEventListener("click", state.searchButtonHandler);
        state.searchButton = button;
        if (!button) return;
        state.searchButtonHandler = (event) => {
            event.preventDefault();
            event.stopPropagation();
            state.runSearch(true);
        };
        button.addEventListener("click", state.searchButtonHandler);
    }

    function initialize(input, options = {}) {
        if (!input) return null;
        const existing = stateByInput.get(input);
        if (existing) {
            existing.options = {...existing.options, ...options};
            bindSearchButton(existing);
            return existing.api;
        }

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
            requestSequence: 0,
            selecting: false,
            searchButton: null,
            searchButtonHandler: null,
            options: {
                ...DEFAULTS,
                minimumQueryLength: Number(input.dataset.smartSearchMinLength || DEFAULTS.minimumQueryLength),
                limit: Number(input.dataset.smartSearchLimit || DEFAULTS.limit),
                ...options,
            },
        };

        const runSearch = async (immediate = false) => {
            window.clearTimeout(state.timer);
            state.request?.abort("replaced");
            const query = input.value.trim();
            if (normalize(query).length < state.options.minimumQueryLength) {
                closeSuggestions(input);
                emit(input, "smart-autocomplete:idle", {query});
                state.options.onIdle?.({input, query});
                return;
            }
            const execute = async () => {
                const sequence = ++state.requestSequence;
                state.request = new AbortController();
                state.lastQuery = query;
                const request = buildRequest(input, query, state);
                renderState(input, state.options.loadingText || "Поиск…", "smart-search-loading");
                emit(input, "smart-autocomplete:loading", {query});
                state.options.onLoading?.({input, query});
                state.searchButton && (state.searchButton.disabled = true);
                try {
                    const payload = await fetchJson(request, {
                        signal: state.request.signal,
                        timeout: state.options.timeoutMs,
                    });
                    if (sequence !== state.requestSequence) return;
                    const items = Array.isArray(payload.items) ? payload.items : [];
                    renderSuggestions(input, items);
                    emit(input, "smart-autocomplete:loaded", {items, payload, query});
                    state.options.onLoaded?.(items, {input, payload, query});
                } catch (error) {
                    if (sequence !== state.requestSequence || error?.smartSearchReason === "external") return;
                    renderState(
                        input,
                        error?.smartSearchReason === "timeout"
                            ? (state.options.timeoutText || "Превышено время ожидания")
                            : (state.options.errorText || "Не удалось выполнить поиск"),
                        "smart-search-error",
                    );
                    emit(input, "smart-autocomplete:error", {error, query});
                    state.options.onError?.(error, {input, query});
                } finally {
                    if (sequence === state.requestSequence) {
                        state.request = null;
                        if (state.searchButton) state.searchButton.disabled = false;
                        state.options.onFinally?.({input, query});
                    }
                }
            };
            if (immediate) return execute();
            state.timer = window.setTimeout(execute, state.options.debounceMs);
        };

        state.runSearch = runSearch;
        state.api = {
            search: () => runSearch(true),
            close: () => closeSuggestions(input),
            cancel(reason = "cancelled") {
                window.clearTimeout(state.timer);
                state.request?.abort(reason);
                state.request = null;
                if (state.searchButton) state.searchButton.disabled = false;
            },
            configure(next) {
                state.options = {...state.options, ...next};
                bindSearchButton(state);
                return this;
            },
            destroy() {
                window.clearTimeout(state.timer);
                state.request?.abort("destroyed");
                if (state.searchButton) state.searchButton.removeEventListener("click", state.searchButtonHandler);
                menu.remove();
                stateByInput.delete(input);
            },
        };
        stateByInput.set(input, state);
        bindSearchButton(state);

        input.addEventListener("input", () => {
            if (!state.selecting && state.options.autoSearch) runSearch(false);
        });
        input.addEventListener("keydown", (event) => {
            if (event.key === "ArrowDown" && !state.menu.hidden && state.items.length) {
                event.preventDefault();
                setActiveOption(input, state.activeIndex + 1);
            } else if (event.key === "ArrowUp" && !state.menu.hidden && state.items.length) {
                event.preventDefault();
                setActiveOption(input, state.activeIndex - 1);
            } else if (event.key === "Enter") {
                event.preventDefault();
                event.stopPropagation();
                const exact = state.items.find((item) => normalize(item.value) === normalize(input.value));
                const selected = !state.menu.hidden
                    ? (state.activeIndex >= 0 ? state.items[state.activeIndex] : exact || state.items[0])
                    : exact;
                if (selected) chooseSuggestion(input, selected, "keyboard");
                else if (state.options.explicitSearch) runSearch(true);
            } else if (event.key === "Escape" && !state.menu.hidden) {
                event.preventDefault();
                closeSuggestions(input);
            }
        });
        input.addEventListener("focus", () => {
            if (state.options.renderMenu && state.items.length && normalize(input.value).length >= state.options.minimumQueryLength) {
                positionMenu(input, menu);
                menu.hidden = false;
                input.setAttribute("aria-expanded", "true");
            }
        });
        input.addEventListener("blur", () => window.setTimeout(() => closeSuggestions(input), 100));
        return state.api;
    }

    document.querySelectorAll("input[data-smart-search]").forEach((input) => initialize(input));

    window.SmartAutocomplete = {
        enhance: initialize,
        close: closeSuggestions,
        search(input) {
            return stateByInput.get(input)?.runSearch?.(true);
        },
        normalize,
        fetchJson,
    };

    const repositionOpenMenus = () => {
        document.querySelectorAll("input[data-smart-search]").forEach((input) => {
            const state = stateByInput.get(input);
            if (state && !state.menu.hidden) positionMenu(input, state.menu);
        });
    };
    window.addEventListener("resize", repositionOpenMenus);
    window.addEventListener("scroll", repositionOpenMenus, true);
})();
