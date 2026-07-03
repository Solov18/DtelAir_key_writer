const themeToggle = document.getElementById("themeToggle");
const themeIcon = document.querySelector(".theme-icon");
const themeText = document.querySelector(".theme-text");

function applyTheme(theme) {
    if (theme === "light") {
        document.body.classList.add("light-theme");
    } else {
        document.body.classList.remove("light-theme");
    }

    if (themeIcon) {
        themeIcon.textContent = theme === "light" ? "🌙" : "☀️";
    }

    if (themeText) {
        themeText.textContent = theme === "light" ? "Тёмная" : "Светлая";
    }

    localStorage.setItem("theme", theme);
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