(() => {
    const SELECTOR = "select:not([data-native-select])";
    const instances = new WeakMap();
    let sequence = 0;

    const normalize = (value) => (
        window.smartSearchNormalize
            ? window.smartSearchNormalize(value)
            : String(value || "")
                .normalize("NFKC")
                .toLocaleLowerCase("ru-RU")
                .replace(/[^\p{L}\p{N}]+/gu, "")
    );
    const chevron = `
        <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="m7 9.5 5 5 5-5"/>
        </svg>`;

    function closeOthers(current) {
        document.querySelectorAll(".app-combobox.is-open").forEach((root) => {
            if (root !== current) root.appCombobox?.close();
        });
    }

    function positionPopup(trigger, popup) {
        if (popup.hidden) return;
        const margin = 10;
        const rect = trigger.getBoundingClientRect();
        const width = Math.min(
            Math.max(rect.width, 250),
            window.innerWidth - margin * 2
        );
        popup.style.width = `${width}px`;
        popup.style.left = `${Math.min(
            Math.max(margin, rect.left),
            window.innerWidth - width - margin
        )}px`;
        const wantedHeight = Math.min(
            popup.scrollHeight,
            window.innerHeight - margin * 2
        );
        const spaceBelow = window.innerHeight - rect.bottom - margin;
        const openAbove = spaceBelow < Math.min(wantedHeight, 260)
            && rect.top > spaceBelow;
        const availableHeight = openAbove ? rect.top - margin : spaceBelow;
        popup.style.maxHeight = `${Math.max(150, availableHeight)}px`;
        popup.style.top = openAbove
            ? `${Math.max(margin, rect.top - Math.min(wantedHeight, availableHeight) - 6)}px`
            : `${rect.bottom + 6}px`;
    }

    function initializeRoot(root) {
        if (!root || root.dataset.comboboxReady === "1") return root?.appCombobox;
        const source = root.querySelector("select, input[type='hidden']");
        const trigger = root.querySelector(".app-combobox__trigger");
        const popup = root.querySelector(".app-combobox__popup");
        const search = root.querySelector(".app-combobox__search");
        const list = root.querySelector('[role="listbox"]');
        const label = root.querySelector("[data-combobox-label]");
        if (!source || !trigger || !popup || !list || !label) return null;

        root.dataset.comboboxReady = "1";
        const listId = `app-combobox-list-${++sequence}`;
        list.id = listId;
        trigger.setAttribute("aria-controls", listId);
        popup.dataset.comboboxPortal = listId;
        document.body.appendChild(popup);
        let activeOption = null;
        let optionButtons = [];
        const visibleOptions = () => optionButtons.filter(
            (item) => !item.hidden && !item.disabled
        );

        function setActive(item) {
            optionButtons.forEach((option) => {
                option.classList.toggle("is-active", option === item);
            });
            activeOption = item || null;
            item?.scrollIntoView({block: "nearest"});
        }

        function close({focusTrigger = false} = {}) {
            if (popup.hidden) return;
            popup.hidden = true;
            trigger.setAttribute("aria-expanded", "false");
            root.classList.remove("is-open");
            if (search) search.value = "";
            optionButtons.forEach((item) => { item.hidden = false; });
            ["top", "left", "width", "max-height"].forEach(
                (name) => popup.style.removeProperty(name)
            );
            if (focusTrigger) trigger.focus();
        }

        function open() {
            if (trigger.disabled) return;
            closeOthers(root);
            popup.hidden = false;
            trigger.setAttribute("aria-expanded", "true");
            root.classList.add("is-open");
            setActive(
                optionButtons.find(
                    (item) => item.getAttribute("aria-selected") === "true"
                ) || visibleOptions()[0]
            );
            positionPopup(trigger, popup);
            window.setTimeout(() => {
                if (search && !search.hidden) search.focus();
                else trigger.focus();
            }, 0);
        }

        function choose(item) {
            if (!item || item.disabled) return;
            source.value = item.dataset.value || "";
            label.textContent = item.dataset.label || item.textContent.trim();
            optionButtons.forEach((option) => {
                option.setAttribute(
                    "aria-selected",
                    option === item ? "true" : "false"
                );
            });
            source.dispatchEvent(new Event("change", {bubbles: true}));
            close({focusTrigger: true});
        }

        function bindOptions() {
            optionButtons = [...list.querySelectorAll('[role="option"]')];
            optionButtons.forEach((item) => {
                if (item.dataset.comboboxOptionReady === "1") return;
                item.dataset.comboboxOptionReady = "1";
                item.addEventListener("click", () => choose(item));
            });
            const selected = optionButtons.find(
                (item) => String(item.dataset.value || "") === String(source.value || "")
            ) || optionButtons[0];
            if (!selected) return;
            label.textContent = selected.dataset.label || selected.textContent.trim();
            optionButtons.forEach((option) => {
                option.setAttribute(
                    "aria-selected",
                    option === selected ? "true" : "false"
                );
            });
        }

        trigger.addEventListener("click", () => {
            if (popup.hidden) open();
            else close({focusTrigger: true});
        });
        search?.addEventListener("input", () => {
            const query = normalize(search.value);
            optionButtons.forEach((item) => {
                item.hidden = Boolean(query)
                    && !normalize(item.dataset.label || item.textContent).includes(query);
            });
            setActive(visibleOptions()[0]);
            positionPopup(trigger, popup);
        });
        const handleKeyboard = (event) => {
            if (event.key === "Tab") {
                close();
                return;
            }
            if (event.key === "Escape") {
                event.preventDefault();
                close({focusTrigger: true});
                return;
            }
            if (popup.hidden && ["ArrowDown", "ArrowUp"].includes(event.key)) {
                event.preventDefault();
                open();
                return;
            }
            if (popup.hidden) return;
            const visible = visibleOptions();
            if (!visible.length) return;
            const currentIndex = Math.max(0, visible.indexOf(activeOption));
            if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                event.preventDefault();
                const step = event.key === "ArrowDown" ? 1 : -1;
                setActive(visible[(currentIndex + step + visible.length) % visible.length]);
            } else if (event.key === "Enter") {
                event.preventDefault();
                choose(activeOption || visible[0]);
            }
        };
        root.addEventListener("keydown", handleKeyboard);
        popup.addEventListener("keydown", handleKeyboard);
        source.addEventListener("change", bindOptions);
        source.addEventListener("focus", () => trigger.focus());
        root.closest("form")?.addEventListener("reset", () => {
            window.setTimeout(bindOptions, 0);
        });
        window.addEventListener("resize", () => {
            if (root.classList.contains("is-open")) positionPopup(trigger, popup);
        }, {passive: true});
        window.addEventListener("scroll", () => {
            if (root.classList.contains("is-open")) positionPopup(trigger, popup);
        }, {passive: true, capture: true});

        bindOptions();
        root.appCombobox = {
            open,
            close,
            refresh: bindOptions,
            popup,
            containsTarget(target) {
                return root.contains(target) || popup.contains(target);
            },
        };
        instances.set(source, root.appCombobox);
        return root.appCombobox;
    }

    function enhanceSelect(select) {
        if (!select || instances.has(select) || select.dataset.comboboxEnhanced === "1") {
            return instances.get(select);
        }
        const originalStyle = window.getComputedStyle(select);
        const originalMargin = [
            originalStyle.marginTop,
            originalStyle.marginRight,
            originalStyle.marginBottom,
            originalStyle.marginLeft,
        ].join(" ");
        const originalHeight = Number.parseFloat(originalStyle.height);
        select.dataset.comboboxEnhanced = "1";
        select.classList.add("app-combobox__source");

        const root = document.createElement("div");
        root.className = "app-combobox app-combobox--select";
        root.dataset.combobox = "";
        root.style.margin = originalMargin;
        root.innerHTML = `
            <button type="button" class="app-combobox__trigger"
                    aria-haspopup="listbox" aria-expanded="false">
                <span data-combobox-label></span>${chevron}
            </button>
            <div class="app-combobox__popup" hidden>
                <input class="app-combobox__search" type="search"
                       placeholder="Найти..." aria-label="Поиск в списке"
                       autocomplete="off">
                <div class="app-combobox__options custom-scroll"
                     role="listbox"></div>
            </div>`;
        select.insertAdjacentElement("afterend", root);
        root.prepend(select);

        const trigger = root.querySelector(".app-combobox__trigger");
        const search = root.querySelector(".app-combobox__search");
        const list = root.querySelector('[role="listbox"]');
        if (Number.isFinite(originalHeight) && originalHeight >= 30) {
            trigger.style.minHeight = `${originalHeight}px`;
        }

        function rebuild() {
            list.replaceChildren(...[...select.options].map((option) => {
                const button = document.createElement("button");
                button.type = "button";
                button.setAttribute("role", "option");
                button.dataset.value = option.value;
                button.dataset.label = option.textContent.trim();
                button.textContent = option.textContent.trim();
                button.disabled = option.disabled;
                button.setAttribute(
                    "aria-selected",
                    option.selected ? "true" : "false"
                );
                return button;
            }));
            trigger.disabled = select.disabled;
            root.classList.toggle("is-disabled", select.disabled);
            const searchable = select.dataset.comboboxSearch === "true"
                || (
                    select.dataset.comboboxSearch !== "false"
                    && select.options.length > 7
                );
            search.hidden = !searchable;
            root.appCombobox?.refresh();
            if (root.classList.contains("is-open")) {
                positionPopup(trigger, root.appCombobox.popup);
            }
        }

        rebuild();
        const instance = initializeRoot(root);
        new MutationObserver(rebuild).observe(select, {
            childList: true,
            subtree: true,
            attributes: true,
            attributeFilter: ["disabled", "label", "selected"],
        });
        return instance;
    }

    function initialize(container = document) {
        container.querySelectorAll?.(SELECTOR).forEach(enhanceSelect);
        container.querySelectorAll?.("[data-combobox]").forEach(initializeRoot);
    }

    document.addEventListener("pointerdown", (event) => {
        document.querySelectorAll(".app-combobox.is-open").forEach((root) => {
            if (!root.appCombobox?.containsTarget(event.target)) {
                root.appCombobox?.close();
            }
        });
    });

    document.addEventListener("DOMContentLoaded", () => {
        initialize();
        new MutationObserver((mutations) => {
            mutations.forEach((mutation) => mutation.addedNodes.forEach((node) => {
                if (node.nodeType !== Node.ELEMENT_NODE) return;
                if (node.matches?.(SELECTOR)) enhanceSelect(node);
                initialize(node);
            }));
        }).observe(document.body, {childList: true, subtree: true});
    });

    window.appCombobox = {initialize, enhanceSelect};
})();
