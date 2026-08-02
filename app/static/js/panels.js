document.addEventListener("DOMContentLoaded", () => {
    const page = document.getElementById("panelsPage");
    if (!page) return;
    const toast = document.getElementById("panelsToast");
    const refreshButton = document.getElementById("refreshPanelsButton");
    const monitorProgress = document.getElementById("panelMonitorProgress");
    let toastTimer = 0;
    let pollTimer = 0;
    let stateRequestPending = false;

    function showToast(message, tone = "success") {
        if (!toast) return;
        window.clearTimeout(toastTimer);
        toast.textContent = message;
        toast.className = `panels-toast is-visible is-${tone}`;
        toastTimer = window.setTimeout(() => toast.classList.remove("is-visible"), 3600);
    }

    function openModal(modal) {
        if (!modal) return;
        modal.hidden = false;
        document.body.classList.add("modal-open");
        window.setTimeout(() => modal.querySelector("input:not([type='hidden']), button")?.focus(), 30);
    }

    function closeModal(modal) {
        if (!modal) return;
        modal.hidden = true;
        if (!document.querySelector(".panels-modal:not([hidden])")) document.body.classList.remove("modal-open");
    }

    document.querySelectorAll("[data-open-modal]").forEach((button) => {
        button.addEventListener("click", () => openModal(document.getElementById(button.dataset.openModal)));
    });
    document.querySelectorAll("[data-close-modal]").forEach((button) => {
        button.addEventListener("click", () => closeModal(button.closest(".panels-modal")));
    });

    document.querySelectorAll(".panels-table tbody tr[data-panel-url]").forEach((row) => {
        const openPanel = () => row.dataset.panelUrl && window.location.assign(row.dataset.panelUrl);
        row.addEventListener("click", (event) => {
            if (!event.target.closest("a, button, input, select, textarea")) openPanel();
        });
        row.addEventListener("keydown", (event) => {
            if (!["Enter", " "].includes(event.key)) return;
            event.preventDefault();
            openPanel();
        });
    });

    const selectedRow = document.querySelector(".panels-table tbody tr.is-selected");
    const tableScroller = document.querySelector(".panels-table-scroll");
    if (selectedRow && tableScroller && selectedRow.offsetTop + selectedRow.offsetHeight > tableScroller.clientHeight) {
        tableScroller.scrollTop = Math.max(0, selectedRow.offsetTop - tableScroller.clientHeight / 3);
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

    const formatNumber = (value, digits, suffix) => (
        value === null || value === undefined || value === ""
            ? "—"
            : `${Number(value).toFixed(digits)}${suffix}`
    );
    const formatDate = (value) => {
        if (!value) return "—";
        const date = new Date(value);
        return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("ru-RU");
    };

    function statusMarkup(panel) {
        return `<span class="panel-status is-${panel.status_tone}"><i></i>${panel.status_name}</span>${
            panel.sip_registered === false || panel.sip_registered === 0
                ? '<small class="panel-sip-flag">SIP не зарегистрирован</small>'
                : ""
        }${
            panel.is_stale ? '<small class="panel-stale-flag">Данные устарели</small>' : ""
        }`;
    }

    function updateStatusElement(element, panel) {
        if (!element) return;
        element.className = `panel-status is-${panel.status_tone}`;
        element.innerHTML = `<i></i>${panel.status_name}`;
    }

    function applyPanel(panel) {
        const row = document.querySelector(`tr[data-panel-id="${panel.id}"]`);
        if (row) {
            const statusCell = row.querySelector('[data-panel-cell="status"]');
            if (statusCell) statusCell.innerHTML = statusMarkup(panel);
            const voltage = row.querySelector('[data-panel-cell="voltage"]');
            if (voltage) {
                voltage.textContent = formatNumber(panel.supply_voltage, 2, " В");
                voltage.className = `panel-voltage is-${panel.voltage_tone}`;
            }
            const temperature = row.querySelector('[data-panel-cell="temperature"]');
            if (temperature) temperature.textContent = formatNumber(panel.temperature, 1, " °C");
            const uptime = row.querySelector('[data-panel-cell="uptime"]');
            if (uptime) uptime.textContent = panel.uptime_text || "—";
            const firmware = row.querySelector('[data-panel-cell="firmware"]');
            if (firmware) firmware.textContent = panel.firmware_version || "—";
        }

        if (String(panel.id) !== String(page.dataset.selectedPanelId || "")) return;
        updateStatusElement(document.querySelector('[data-inspector-field="status"]'), panel);
        updateStatusElement(document.querySelector('[data-inspector-field="health_status"]'), panel);
        const values = {
            device_model: panel.device_model || "—",
            firmware_version: panel.firmware_version || "—",
            supply_voltage: formatNumber(panel.supply_voltage, 2, " В"),
            temperature: formatNumber(panel.temperature, 1, " °C"),
            uptime_text: panel.uptime_text || "—",
            last_online_at: formatDate(panel.last_online_at),
            last_checked_at: formatDate(panel.last_checked_at),
        };
        Object.entries(values).forEach(([field, value]) => {
            const element = document.querySelector(`[data-inspector-field="${field}"]`);
            if (element) element.textContent = value;
        });
        const power = document.querySelector('[data-inspector-field="supply_voltage"]');
        if (power) power.className = `is-${panel.voltage_tone}`;
        const sip = document.querySelector('[data-inspector-field="sip_registered"]');
        if (sip) {
            const failed = panel.sip_registered === false || panel.sip_registered === 0;
            sip.textContent = panel.sip_registered === null || panel.sip_registered === undefined
                ? "—"
                : failed ? "Нет — требуется проверка" : "Есть";
            sip.classList.toggle("is-sip-error", failed);
        }
        const error = document.querySelector('[data-inspector-field="last_error"]');
        if (error) {
            error.textContent = panel.last_error || "";
            error.hidden = !panel.last_error;
        }
    }

    function applyStatistics(statistics) {
        ["total", "online", "offline", "errors", "disabled", "sip_failed", "unchecked", "stale"].forEach((name) => {
            const element = document.querySelector(`[data-stat="${name}"]`);
            if (element) element.textContent = statistics[name] ?? 0;
        });
        const percent = document.querySelector('[data-stat-percent="online"]');
        if (percent) percent.textContent = `${statistics.online_percent || 0}%`;
    }

    function applyMonitor(monitor) {
        const running = ["queued", "running"].includes(monitor.status);
        page.dataset.monitorStatus = monitor.status;
        if (refreshButton) {
            refreshButton.disabled = running || refreshButton.dataset.unavailable === "1";
            refreshButton.classList.toggle("is-loading", running);
        }
        if (!monitorProgress) return;
        const total = Number(monitor.total || 0);
        const completed = Number(monitor.completed || 0);
        const percentage = total ? Math.min(100, completed / total * 100) : 0;
        const message = monitorProgress.querySelector("[data-monitor-message]");
        const bar = monitorProgress.querySelector("[data-monitor-bar]");
        const time = monitorProgress.querySelector("[data-monitor-time]");
        if (bar) bar.style.width = `${percentage}%`;
        if (message) {
            if (monitor.status === "queued") message.textContent = "Обновление ожидает запуска";
            else if (monitor.status === "running") message.textContent = `Проверено ${completed} из ${total}`;
            else if (monitor.status === "failed") message.textContent = "Цикл завершился с ошибкой";
            else message.textContent = "Мониторинг готов";
        }
        if (time && monitor.finished_at) time.textContent = `Последний полный цикл: ${formatDate(monitor.finished_at)}`;
    }

    function stateUrl() {
        const params = new URLSearchParams(window.location.search);
        params.delete("selected_panel_id");
        return `/panels/monitor/state?${params.toString()}`;
    }

    async function pollState() {
        if (stateRequestPending) return;
        stateRequestPending = true;
        window.clearTimeout(pollTimer);
        try {
            const response = await fetch(stateUrl(), {headers: {"Accept": "application/json"}});
            const result = await response.json();
            if (!response.ok || !result.ok) throw new Error(result.error || "Не удалось обновить состояние");
            applyMonitor(result.monitor);
            applyStatistics(result.statistics);
            result.items.forEach(applyPanel);
            const active = ["queued", "running"].includes(result.monitor.status);
            pollTimer = window.setTimeout(pollState, active ? 1400 : 10000);
        } catch (error) {
            pollTimer = window.setTimeout(pollState, 10000);
        } finally {
            stateRequestPending = false;
        }
    }

    if (refreshButton) {
        refreshButton.dataset.unavailable = refreshButton.disabled && !["queued", "running"].includes(page.dataset.monitorStatus) ? "1" : "0";
        refreshButton.addEventListener("click", async () => {
            refreshButton.disabled = true;
            try {
                const response = await fetch("/panels/monitor/start", {method: "POST"});
                const result = await response.json().catch(() => ({}));
                if (!response.ok || !result.ok) throw new Error(result.error || "Не удалось запустить мониторинг");
                applyMonitor(result.monitor);
                showToast(result.message || "Мониторинг запущен");
                pollState();
            } catch (error) {
                showToast(error.message || "Ошибка запуска мониторинга", "error");
                refreshButton.disabled = false;
            }
        });
    }

    async function checkOne(panelId, button) {
        if (!panelId || !button || button.disabled) return;
        const original = button.innerHTML;
        button.disabled = true;
        button.classList.add("is-loading");
        if (button.id === "checkSelectedPanel") button.textContent = "Проверяем…";
        const statusCell = document.querySelector(`tr[data-panel-id="${panelId}"] [data-panel-cell="status"]`);
        if (statusCell) statusCell.innerHTML = '<span class="panel-status is-info"><i></i>Проверяется</span>';
        try {
            const response = await fetch(`/panels/${panelId}/check`, {method: "POST"});
            const result = await response.json().catch(() => ({}));
            if (!response.ok || !result.ok) throw new Error(result.error || "Проверка не выполнена");
            applyPanel(result.panel);
            applyStatistics(result.statistics);
            showToast("Состояние панели обновлено");
        } catch (error) {
            showToast(error.message || "Ошибка проверки", "error");
            pollState();
        } finally {
            button.disabled = false;
            button.classList.remove("is-loading");
            button.innerHTML = original;
        }
    }

    document.querySelectorAll("[data-check-panel]").forEach((button) => {
        button.addEventListener("click", () => checkOne(Number(button.dataset.checkPanel), button));
    });
    const selectedCheck = document.getElementById("checkSelectedPanel");
    if (selectedCheck) selectedCheck.addEventListener("click", () => checkOne(Number(selectedCheck.dataset.panelId), selectedCheck));

    const rebootButton = document.getElementById("rebootPanelButton");
    if (rebootButton) {
        rebootButton.addEventListener("click", async () => {
            const accepted = await window.showDangerConfirm({
                title: "Перезагрузить панель?",
                message: "Связь с выбранной панелью пропадёт на время запуска устройства.",
                confirmText: "Перезагрузить",
                cancelText: "Отмена",
                source: rebootButton,
            });
            if (!accepted) return;
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

    const snapshotButton = document.getElementById("loadPanelSnapshot");
    if (snapshotButton) {
        snapshotButton.addEventListener("click", () => {
            const placeholder = document.getElementById("panelCameraPlaceholder");
            if (!placeholder) return;
            snapshotButton.disabled = true;
            snapshotButton.textContent = "Загружаем…";
            const image = new Image();
            image.id = "panelCameraImage";
            image.alt = `Камера панели ${snapshotButton.dataset.panelId}`;
            image.addEventListener("load", () => {
                placeholder.replaceWith(image);
                const badge = document.createElement("span");
                badge.className = "panel-live-badge";
                badge.textContent = "КАДР";
                image.closest(".panel-camera")?.appendChild(badge);
            });
            image.addEventListener("error", () => {
                snapshotButton.disabled = false;
                snapshotButton.textContent = "Повторить загрузку";
                showToast("Не удалось получить кадр с панели", "error");
            });
            image.src = `/panels/${snapshotButton.dataset.panelId}/snapshot?t=${Date.now()}`;
        });
    }

    if (refreshButton && ["queued", "running"].includes(page.dataset.monitorStatus)) {
        refreshButton.disabled = true;
        refreshButton.classList.add("is-loading");
    }
    pollState();
});
