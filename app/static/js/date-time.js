(function () {
    "use strict";

    const pad = (value) => String(value).padStart(2, "0");

    function formatDateTime(value, options = {}) {
        if (value === null || value === undefined || value === "") return "—";

        const parsed = value instanceof Date ? value : new Date(value);
        if (Number.isNaN(parsed.getTime())) return String(value);

        const date = `${pad(parsed.getDate())}.${pad(parsed.getMonth() + 1)}.${parsed.getFullYear()}`;
        const time = `${pad(parsed.getHours())}:${pad(parsed.getMinutes())}`;
        const seconds = options.withSeconds ? `:${pad(parsed.getSeconds())}` : "";
        return `${date} ${time}${seconds}`;
    }

    window.formatDateTime = formatDateTime;
}());
