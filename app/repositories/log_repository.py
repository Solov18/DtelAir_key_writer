from app.db import db


ACTION_NAMES = {
    "user_create": "Создание пользователя",
    "user_delete": "Удаление пользователя",
    "user_password_change": "Смена пароля",

    "resident_manual": "Обычная запись",
    "message": "Из сообщения",
    "uk": "Запись УК",
    "employee": "Запись сотрудника",

    "import_keys": "Импорт ключей",
    "import_panels": "Импорт панелей",

    "panel_create": "Добавление панели",
    "panel_delete": "Удаление панели",
    "employee_create": "Добавление сотрудника",
    "employee_delete": "Удаление сотрудника",
    "uk_create": "Создание УК",
    "uk_delete": "Удаление УК",
}


STATUS_NAMES = {
    "success": "Успешно",
    "SUCCESS": "Успешно",
    "DRY_RUN": "Тест",
    "ERROR": "Ошибка",
    "error": "Ошибка",
    "NO_COOKIE": "Ошибка CRM",
}


def _normalize_row(row: dict) -> dict:
    action = row.get("action") or row.get("mode") or "unknown"

    action_name = ACTION_NAMES.get(action, action)

    user_name = (
        row.get("user_full_name")
        or row.get("username")
        or "Система"
    )

    user_role = row.get("user_role") or ""

    object_type = row.get("object_type") or ""
    object_name = row.get("object_name") or ""

    if not object_name:
        if row.get("printed_number"):
            object_type = "Ключ"
            object_name = row.get("printed_number")
        elif row.get("hex_value") and row.get("hex_value") != "-":
            object_type = "HEX"
            object_name = row.get("hex_value")
        elif row.get("panel_name"):
            object_type = "Панель"
            object_name = row.get("panel_name")
        else:
            object_name = "—"

    details = row.get("details") or ""

    if not details:
        parts = []

        if row.get("address"):
            parts.append(row.get("address"))

        if row.get("apartment") or row.get("flat_num"):
            parts.append(f"кв. {row.get('apartment') or row.get('flat_num')}")

        if row.get("panel_name"):
            parts.append(row.get("panel_name"))

        if row.get("mac"):
            parts.append(row.get("mac"))

        details = " / ".join(parts)

    if not details:
        details = row.get("response") or "—"

    status = row.get("status") or "success"
    status_name = STATUS_NAMES.get(status, status)

    return {
        **row,
        "action_key": action,
        "action_name": action_name,
        "user_name": user_name,
        "user_role_name": "Администратор" if user_role == "admin" else "Оператор" if user_role == "operator" else "—",
        "object_type_view": object_type,
        "object_name_view": object_name,
        "details_view": details,
        "status_name": status_name,
    }


def get_last_operations(limit: int = 500) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM operation_log
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        return [_normalize_row(dict(row)) for row in rows]


def get_recent_operations(limit: int = 5) -> list[dict]:
    return get_last_operations(limit)