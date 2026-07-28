(() => {
    const normalize = (value) => (
        window.smartSearchNormalize
            ? window.smartSearchNormalize(value)
            : String(value || "").toLocaleLowerCase("ru-RU").replace(/[^\p{L}\p{N}]+/gu, "")
    );

    function initCombobox(root, index) {
        const hidden = root.querySelector('input[type="hidden"]');
        const trigger = root.querySelector(".app-combobox__trigger");
        const popup = root.querySelector(".app-combobox__popup");
        const search = root.querySelector(".app-combobox__search");
        const options = [...root.querySelectorAll('[role="option"]')];
        const label = root.querySelector("[data-combobox-label]");
        if (!hidden || !trigger || !popup || !search || !options.length) return;

        const listId = `app-combobox-list-${index}`;
        popup.querySelector('[role="listbox"]')?.setAttribute("id", listId);
        trigger.setAttribute("aria-controls", listId);
        let activeIndex = Math.max(0, options.findIndex((item) => item.getAttribute("aria-selected") === "true"));

        const visibleOptions = () => options.filter((item) => !item.hidden);

        function setActive(item) {
            options.forEach((option) => option.classList.toggle("is-active", option === item));
            activeIndex = Math.max(0, visibleOptions().indexOf(item));
            item?.scrollIntoView({block: "nearest"});
        }

        function close({focusTrigger = false} = {}) {
            popup.hidden = true;
            trigger.setAttribute("aria-expanded", "false");
            root.classList.remove("is-open");
            search.value = "";
            options.forEach((item) => { item.hidden = false; });
            if (focusTrigger) trigger.focus();
        }

        function open() {
            document.querySelectorAll(".app-combobox.is-open").forEach((item) => {
                if (item !== root) item.querySelector(".app-combobox__trigger")?.click();
            });
            popup.hidden = false;
            trigger.setAttribute("aria-expanded", "true");
            root.classList.add("is-open");
            const selected = options.find((item) => item.getAttribute("aria-selected") === "true") || options[0];
            setActive(selected);
            window.setTimeout(() => search.focus(), 0);
        }

        function choose(item) {
            hidden.value = item.dataset.value || "";
            label.textContent = item.textContent.trim();
            options.forEach((option) => option.setAttribute("aria-selected", option === item ? "true" : "false"));
            hidden.dispatchEvent(new Event("change", {bubbles: true}));
            close({focusTrigger: true});
        }

        trigger.addEventListener("click", () => {
            if (popup.hidden) open();
            else close();
        });
        options.forEach((item) => item.addEventListener("click", () => choose(item)));
        search.addEventListener("input", () => {
            const query = normalize(search.value);
            options.forEach((item) => {
                item.hidden = Boolean(query) && !normalize(item.textContent).includes(query);
            });
            setActive(visibleOptions()[0]);
        });
        root.addEventListener("keydown", (event) => {
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
            if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                event.preventDefault();
                const step = event.key === "ArrowDown" ? 1 : -1;
                setActive(visible[(activeIndex + step + visible.length) % visible.length]);
            } else if (event.key === "Enter") {
                event.preventDefault();
                choose(visible[activeIndex] || visible[0]);
            }
        });
        document.addEventListener("pointerdown", (event) => {
            if (!root.contains(event.target)) close();
        });
    }

    document.addEventListener("DOMContentLoaded", () => {
        document.querySelectorAll("[data-combobox]").forEach(initCombobox);
    });
})();
