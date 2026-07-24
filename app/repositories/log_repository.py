from app.db import db
from app.presentation import operation_status_name, operation_status_tone


ACTION_NAMES = {
    "user_create": "Создание пользователя",
    "user_delete": "Удаление пользователя",
    "user_password_change": "Смена пароля",

    "resident_manual": "Обычная запись",
    "resident": "Из сообщения",
    "message": "Из сообщения",
    "uk": "Запись УК",
    "employee": "Запись сотрудника",

    "import_keys": "Импорт ключей",
    "key_type_create": "Создание типа ключа",
    "key_type_update": "Изменение типа ключа",
    "keys_prepare": "Подготовка партии ключей",
    "key_hex_scan": "Считывание HEX ключа",
    "key_update": "Изменение ключа",
    "key_status_change": "Изменение статуса ключа",
    "key_release": "Освобождение ключа",
    "import_panels": "Импорт панелей",

    "panel_create": "Добавление панели",
    "panel_update": "Изменение панели",
    "panel_delete": "Удаление панели",
    "panel_import": "Импорт панелей",
    "panel_status_refresh": "Проверка состояния панелей",
    "panel_reboot": "Перезагрузка панели",
    "panel_enable": "Возврат панели в работу",
    "panel_disable": "Отключение панели в учёте",
    "employee_create": "Добавление сотрудника",
    "employee_update": "Изменение сотрудника",
    "employee_dismiss": "Увольнение сотрудника",
    "employee_restore": "Восстановление сотрудника",
    "employee_key_issue": "Выдача ключа сотруднику",
    "employee_key_close": "Закрытие ключа сотрудника",
    "employee_key_comment": "Комментарий к ключу сотрудника",
    "employee_key_history_update": "Изменение истории ключа",
    "employee_key_remove": "Деактивация ключа сотрудника",
    "employee_delete": "Увольнение сотрудника",
    "uk_create": "Создание УК",
    "uk_update": "Изменение УК",
    "uk_delete": "Удаление УК",
    "uk_panels_add": "Добавление панелей в УК",
    "uk_panel_remove": "Удаление панели из УК",
    "uk_keys_add": "Добавление ключей в УК",
    "uk_key_remove": "Удаление ключа из УК",
}


def normalize_operation_row(row: dict) -> dict:
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
    status_name = operation_status_name(status)
    status_tone = operation_status_tone(status)

    return {
        **row,
        "action_key": action,
        "action_name": action_name,
        "user_name": user_name,
        "user_role_name": (
            "Администратор"
            if user_role == "admin"
            else "Оператор"
            if user_role == "operator"
            else "Наблюдатель"
            if user_role == "viewer"
            else "—"
        ),
        "object_type_view": object_type,
        "object_name_view": object_name,
        "details_view": details,
        "status_name": status_name,
        "status_tone": status_tone,
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

        return [normalize_operation_row(dict(row)) for row in rows]


def get_recent_operations(limit: int = 5) -> list[dict]:
    return get_last_operations(limit)
