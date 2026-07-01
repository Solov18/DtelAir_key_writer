const themeToggle = document.getElementById("themeToggle");
const themeIcon = document.querySelector(".theme-icon");
const themeText = document.querySelector(".theme-text");

function applyTheme(theme) {
    document.body.classList.toggle("light-theme", theme === "light");

    if (themeIcon && themeText) {
        if (theme === "light") {
            themeIcon.textContent = "🌙";
            themeText.textContent = "Тёмная";
        } else {
            themeIcon.textContent = "☀️";
            themeText.textContent = "Светлая";
        }
    }

    localStorage.setItem("theme", theme);
}

const savedTheme = localStorage.getItem("theme") || "dark";
applyTheme(savedTheme);

if (themeToggle) {
    themeToggle.addEventListener("click", () => {
        const isLight = document.body.classList.contains("light-theme");
        applyTheme(isLight ? "dark" : "light");
    });
}