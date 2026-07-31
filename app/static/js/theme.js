const themeToggle = document.getElementById("themeToggle");
const themeText = document.querySelector(".theme-text");

function applyTheme(theme) {
    const isLight = theme === "light";

    if (isLight) {
        document.body.classList.add("light-theme");
    } else {
        document.body.classList.remove("light-theme");
    }

    document.documentElement.style.colorScheme = isLight ? "light" : "dark";

    if (themeText) {
        themeText.textContent = isLight ? "Тёмная" : "Светлая";
    }

    if (themeToggle) {
        themeToggle.setAttribute("aria-pressed", String(isLight));
        themeToggle.setAttribute(
            "aria-label",
            isLight ? "Включить тёмную тему" : "Включить светлую тему",
        );
    }

    localStorage.setItem("theme", theme);
    window.dispatchEvent(
        new CustomEvent("app:themechange", { detail: { theme } }),
    );
}

const savedTheme = localStorage.getItem("theme") || "dark";
applyTheme(savedTheme);

if (themeToggle) {
    themeToggle.addEventListener("click", () => {
        const currentTheme = document.body.classList.contains("light-theme")
            ? "light"
            : "dark";

        applyTheme(currentTheme === "light" ? "dark" : "light");
    });
}
