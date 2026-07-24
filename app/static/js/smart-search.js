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

    const stateByInput = new WeakMap();

    function closeSuggestions(input) {
        const state = stateByInput.get(input);
        if (!state) {
            return;
        }
        state.menu.hidden = true;
        state.activeIndex = -1;
        input.setAttribute("aria-expanded", "false");
    }

    function positionMenu(input, menu) {
        const rect = input.getBoundingClientRect();
        menu.style.left = `${Math.max(8, rect.left)}px`;
        menu.style.top = `${rect.bottom + 6}px`;
        menu.style.width = `${Math.max(280, rect.width)}px`;
        menu.style.maxWidth = `${Math.max(280, window.innerWidth - rect.left - 8)}px`;
    }

    function chooseSuggestion(input, item) {
        input.value = item.value;
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.dispatchEvent(new Event("change", { bubbles: true }));
        closeSuggestions(input);
        input.focus();
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
            closeSuggestions(input);
            return;
        }

        items.forEach((item, index) => {
            const option = document.createElement("button");
            option.type = "button";
            option.className = "smart-search-option";
            option.setAttribute("role", "option");
            option.dataset.index = String(index);

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
            arrow.textContent = "↵";
            option.append(text, arrow);

            option.addEventListener("mousedown", (event) => {
                event.preventDefault();
                chooseSuggestion(input, item);
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

        state.activeIndex = (
            nextIndex + state.items.length
        ) % state.items.length;

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
    }

    document.querySelectorAll("input[data-smart-search]").forEach((input) => {
        const menu = document.createElement("div");
        menu.className = "smart-search-menu";
        menu.setAttribute("role", "listbox");
        menu.hidden = true;
        document.body.appendChild(menu);

        input.setAttribute("autocomplete", "off");
        input.setAttribute("aria-autocomplete", "list");
        input.setAttribute("aria-expanded", "false");

        const state = {
            menu,
            items: [],
            activeIndex: -1,
            timer: 0,
            request: null,
        };
        stateByInput.set(input, state);

        input.addEventListener("input", () => {
            window.clearTimeout(state.timer);
            state.request?.abort();

            const query = input.value.trim();
            if (normalize(query).length < 2) {
                closeSuggestions(input);
                return;
            }

            state.timer = window.setTimeout(async () => {
                state.request = new AbortController();
                const params = new URLSearchParams({
                    q: query,
                    scope: input.dataset.smartSearch || "universal",
                    limit: "8",
                });

                try {
                    const response = await fetch(
                        `/api/search/suggestions?${params}`,
                        {
                            signal: state.request.signal,
                            headers: { Accept: "application/json" },
                        }
                    );
                    if (!response.ok) {
                        throw new Error(`HTTP ${response.status}`);
                    }
                    const payload = await response.json();
                    renderSuggestions(input, payload.items || []);
                } catch (error) {
                    if (error.name !== "AbortError") {
                        closeSuggestions(input);
                    }
                }
            }, 180);
        });

        input.addEventListener("keydown", (event) => {
            if (state.menu.hidden) {
                return;
            }

            if (event.key === "ArrowDown") {
                event.preventDefault();
                setActiveOption(input, state.activeIndex + 1);
            } else if (event.key === "ArrowUp") {
                event.preventDefault();
                setActiveOption(input, state.activeIndex - 1);
            } else if (event.key === "Enter" && state.activeIndex >= 0) {
                event.preventDefault();
                chooseSuggestion(input, state.items[state.activeIndex]);
            } else if (event.key === "Escape") {
                closeSuggestions(input);
            }
        });

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
    });

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
