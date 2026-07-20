STATUS_LABELS = {
    "success": "Успешно",
    "SUCCESS": "Успешно",
    "warning": "С предупреждениями",
    "DRY_RUN": "Без отправки в CRM",
    "ERROR": "Ошибка",
    "error": "Ошибка",
    "NO_COOKIE": "Требуется вход в CRM",
    "AUTH_REQUIRED": "Требуется вход в CRM",
    "CRM_ERROR": "CRM отклонила операцию",
    "INVALID_RESPONSE": "Некорректный ответ CRM",
    "CONNECTION_ERROR": "Нет связи с CRM",
    "TIMEOUT": "CRM не ответила",
    "VALIDATION_ERROR": "Некорректные данные",
    "KEY_UNAVAILABLE": "Ключ недоступен для записи",
}


def operation_status_name(status: str | None) -> str:
    key = str(status or "success").strip()

    if key.startswith("HTTP_"):
        return f"Ошибка CRM (HTTP {key.removeprefix('HTTP_')})"

    return STATUS_LABELS.get(key, "Неизвестный статус")


def operation_status_tone(status: str | None) -> str:
    key = str(status or "success").strip()

    if key in {"success", "SUCCESS"}:
        return "success"

    if key in {"DRY_RUN", "warning"}:
        return "warning"

    return "error"
