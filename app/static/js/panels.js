document.addEventListener("DOMContentLoaded", () => {
    const page = document.getElementById("panelsPage");
    const toast = document.getElementById("panelsToast");
    let toastTimer;

    function showToast(message, tone = "success") {
        if (!toast) return;
        clearTimeout(toastTimer);
        toast.textContent = message;
        toast.className = `panels-toast is-visible is-${tone}`;
        toastTimer = setTimeout(() => toast.classList.remove("is-visible"), 3200);
    }

    function openModal(modal) {
        if (!modal) return;
        modal.hidden = false;
        document.body.classList.add("modal-open");
        const firstInput = modal.querySelector("input:not([type='hidden']), select, button");
        if (firstInput) setTimeout(() => firstInput.focus(), 30);
    }

    function closeModal(modal) {
        if (!modal) return;
        modal.hidden = true;
        if (!document.querySelector(".panels-modal:not([hidden])")) {
            document.body.classList.remove("modal-open");
        }
    }

    document.querySelectorAll("[data-open-modal]").forEach((button) => {
        button.addEventListener("click", () => openModal(document.getElementById(button.dataset.openModal)));
    });

    document.querySelectorAll("[data-close-modal]").forEach((button) => {
        button.addEventListener("click", () => closeModal(button.closest(".panels-modal")));
    });

    document.querySelectorAll(".panels-table tbody tr[data-panel-url]").forEach((row) => {
        const openPanel = () => {
            if (row.dataset.panelUrl) window.location.assign(row.dataset.panelUrl);
        };
        row.addEventListener("click", (event) => {
            if (event.target.closest("a, button, input, select, textarea")) return;
            openPanel();
        });
        row.addEventListener("keydown", (event) => {
            if (event.key !== "Enter" && event.key !== " ") return;
            event.preventDefault();
            openPanel();
        });
    });

    const selectedRow = document.querySelector(".panels-table tbody tr.is-selected");
    const tableScroller = document.querySelector(".panels-table-scroll");
    if (selectedRow && tableScroller) {
        const rowTop = selectedRow.offsetTop;
        const rowBottom = rowTop + selectedRow.offsetHeight;
        if (rowBottom > tableScroller.clientHeight) {
            tableScroller.scrollTop = Math.max(0, rowTop - tableScroller.clientHeight / 3);
        }
    }

    const editModal = document.getElementById("panelEditModal");
    document.querySelectorAll("[data-edit-panel]").forEach((button) => {
        button.addEventListener("click", () => {
            document.getElementById("editPanelId").value = button.dataset.id || "";
            document.getElementById("editPanelAddress").value = button.dataset.address || "";
            document.getElementById("editPanelEntrance").value = button.dataset.entrance || "";
            document.getElementById("editPanelIp").value = button.dataset.ip || "";
            document.getElementById("editPanelMac").value = button.dataset.mac || "";
            openModal(editModal);
        });
    });

    document.querySelectorAll("form[data-confirm]").forEach((form) => {
        form.addEventListener("submit", (event) => {
            if (!window.confirm(form.dataset.confirm || "Выполнить действие?")) {
                event.preventDefault();
            }
        });
    });

    async function refreshPanels(panelIds, button) {
        if (!panelIds.length) {
            showToast("Нет панелей для проверки", "warning");
            return;
        }
        const originalText = button?.innerHTML;
        if (button) {
            button.disabled = true;
            button.classList.add("is-loading");
            button.innerHTML = "<svg class='refresh-icon' viewBox='0 0 24 24' aria-hidden='true'><path d='M20 11a8 8 0 1 0-2.3 5.7'/><path d='M20 5v6h-6'/></svg> Проверяем связь…";
        }
        try {
            const response = await fetch("/panels/status/refresh", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({panel_ids: panelIds}),
            });
            const result = await response.json().catch(() => ({}));
            if (!response.ok || !result.ok) throw new Error(result.error || "Не удалось проверить панели");
            showToast(result.message || "Статусы обновлены");
            setTimeout(() => window.location.reload(), 650);
        } catch (error) {
            showToast(error.message || "Ошибка проверки", "error");
            if (button) {
                button.disabled = false;
                button.classList.remove("is-loading");
                button.innerHTML = originalText;
            }
        }
    }

    const refreshButton = document.getElementById("refreshPanelsButton");
    if (refreshButton && page) {
        refreshButton.addEventListener("click", () => {
            let panelIds = [];
            try {
                panelIds = JSON.parse(page.dataset.panelIds || "[]").map(Number).filter(Boolean);
            } catch (_) {
                panelIds = [];
            }
            refreshPanels(panelIds, refreshButton);
        });
    }

    const checkSelectedButton = document.getElementById("checkSelectedPanel");
    if (checkSelectedButton) {
        checkSelectedButton.addEventListener("click", () => {
            refreshPanels([Number(checkSelectedButton.dataset.panelId)], checkSelectedButton);
        });
    }

    const rebootButton = document.getElementById("rebootPanelButton");
    if (rebootButton) {
        rebootButton.addEventListener("click", async () => {
            if (!window.confirm("Перезагрузить выбранную панель? Связь пропадёт на время запуска устройства.")) return;
            rebootButton.disabled = true;
            const originalText = rebootButton.textContent;
            rebootButton.textContent = "Отправляем команду…";
            try {
                const response = await fetch(`/panels/${rebootButton.dataset.panelId}/reboot`, {method: "POST"});
                const result = await response.json().catch(() => ({}));
                if (!response.ok || !result.ok) throw new Error(result.error || "Команда не выполнена");
                showToast(result.message || "Команда отправлена");
            } catch (error) {
                showToast(error.message || "Ошибка перезагрузки", "error");
            } finally {
                rebootButton.disabled = false;
                rebootButton.textContent = originalText;
            }
        });
    }

    const cameraImage = document.getElementById("panelCameraImage");
    if (cameraImage) {
        cameraImage.addEventListener("error", () => {
            const camera = cameraImage.closest(".panel-camera");
            cameraImage.remove();
            camera?.querySelector(".panel-live-badge")?.remove();
            if (camera) {
                const placeholder = document.createElement("div");
                placeholder.className = "panel-camera-placeholder";
                placeholder.innerHTML = "<b>Не удалось получить кадр</b><span>Проверьте связь и доступ API.</span>";
                camera.appendChild(placeholder);
            }
        });
    }
});
