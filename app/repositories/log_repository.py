import re
from datetime import date, datetime

from app.audit_security import redact_audit_text
from app.db import db
from app.presentation import operation_status_name, operation_status_tone


ACTION_NAMES = {
    "user_create": "Создание пользователя",
    "user_delete": "Удаление пользователя",
    "user_password_change": "Смена пароля",
    "user_update": "Изменение пользователя",
    "user_status_change": "Изменение доступа пользователя",
    "role_create": "Создание роли",
    "role_update": "Изменение роли",
    "role_delete": "Удаление роли",
    "settings_training_mode": "Изменение режима работы",
    "settings_crm_check": "Проверка подключения CRM",
    "settings_panel_api_check": "Проверка подключения API панелей",
    "settings_monitor_update": "Изменение параметров мониторинга",

    "resident_manual": "Обычная запись",
    "resident": "Из сообщения",
    "message": "Из сообщения",
    "uk": "Запись УК",
    "employee": "Запись сотрудника",

    "import_keys": "Импорт ключей",
    "legacy_issued_import": "Перенос ранее выданных ключей",
    "legacy_free_import": "Перенос свободных ключей",
    "key_type_create": "Создание типа ключа",
    "key_type_update": "Изменение типа ключа",
    "keys_prepare": "Подготовка партии ключей",
    "key_hex_scan": "Считывание HEX ключа",
    "key_update": "Изменение ключа",
    "key_assignment_update": "Изменение назначения ключа",
    "key_status_change": "Изменение статуса ключа",
    "key_release": "Освобождение ключа",
    "import_panels": "Импорт панелей",

    "panel_create": "Добавление панели",
    "panel_update": "Изменение панели",
    "panel_delete": "Удаление панели",
    "panel_import": "Импорт панелей",
    "panel_status_refresh": "Проверка состояния панелей",
    "panel_check": "Проверка панели",
    "panel_monitor_request": "Запуск мониторинга панелей",
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
    "uk_archive": "Архивирование УК",
    "uk_panel_add": "Закрепление панели за УК",
    "uk_panel_update": "Изменение квартиры УК",
    "uk_panel_detach": "Открепление панели от УК",
    "uk_key_program": "Запись ключа УК",
    "uk_key_unlink": "Удаление учётной связи ключа УК",
    "uk_key_remove_from_panel": "Удаление ключа УК из CRM панели",
}

OBJECT_TYPE_NAMES = {
    "user": "Пользователь",
    "employee": "Сотрудник",
    "key": "Ключ",
    "panel": "Панель",
    "uk": "УК",
    "role": "Роль",
    "settings": "Настройки",
    "mode": "Режим работы",
    "other": "Другое",
}

_OBJECT_FILTERS = {
    "mode": "(action = 'settings_training_mode' OR LOWER(COALESCE(object_type, '')) LIKE '%режим%')",
    "user": "(action LIKE 'user_%' OR LOWER(COALESCE(object_type, '')) LIKE '%пользоват%')",
    "employee": "(employee_id IS NOT NULL OR action LIKE 'employee_%' OR LOWER(COALESCE(object_type, '')) LIKE '%сотрудник%')",
    "panel": "(panel_id IS NOT NULL OR action LIKE 'panel_%' OR action = 'import_panels' OR LOWER(COALESCE(object_type, '')) LIKE '%панел%')",
    "uk": "(uk_group_id IS NOT NULL OR action LIKE 'uk_%' OR action = 'uk' OR LOWER(COALESCE(object_type, '')) IN ('ук', 'управляющая компания'))",
    "role": "(action LIKE 'role_%' OR LOWER(COALESCE(object_type, '')) LIKE '%рол%')",
    "settings": "(action <> 'settings_training_mode' AND (action LIKE 'settings_%' OR LOWER(COALESCE(object_type, '')) LIKE '%настройк%'))",
    "key": "(key_id IS NOT NULL OR action LIKE 'key_%' OR action IN ('resident', 'resident_manual', 'message', 'import_keys', 'keys_prepare') OR LOWER(COALESCE(object_type, '')) LIKE '%ключ%')",
}

_SEARCH_CLEANUP = re.compile(r"[^0-9a-zа-я]+", re.IGNORECASE)


def _smart_norm(value: object) -> str:
    return _SEARCH_CLEANUP.sub("", str(value or "").lower().replace("ё", "е"))


def _iso_date(value: date | datetime | str | None) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return date.fromisoformat(str(value).strip()).isoformat()


def _build_operation_filters(
    *,
    date_from: date | datetime | str | None = None,
    date_to: date | datetime | str | None = None,
    user_id: int | None = None,
    action: str | None = None,
    object_type: str | None = None,
    status: str | None = None,
    search: str | None = None,
) -> tuple[str, list[object]]:
    conditions: list[str] = []
    params: list[object] = []

    start_date = _iso_date(date_from)
    end_date = _iso_date(date_to)
    if start_date:
        conditions.append("SUBSTRING(COALESCE(created_at, '') FROM 1 FOR 10) >= ?")
        params.append(start_date)
    if end_date:
        conditions.append("SUBSTRING(COALESCE(created_at, '') FROM 1 FOR 10) <= ?")
        params.append(end_date)

    if user_id is not None:
        conditions.append(
            """LOWER(COALESCE(username, '')) = LOWER(
                COALESCE((SELECT login FROM users WHERE id = ?), '')
            )"""
        )
        params.append(int(user_id))

    if action:
        conditions.append("action = ?")
        params.append(action)

    if object_type:
        object_key = object_type.strip().lower()
        if object_key == "other":
            known = " OR ".join(_OBJECT_FILTERS.values())
            conditions.append(f"NOT ({known})")
        elif object_key in _OBJECT_FILTERS:
            conditions.append(_OBJECT_FILTERS[object_key])

    if status == "success":
        conditions.append("LOWER(COALESCE(status, '')) = 'success'")
    elif status == "warning":
        conditions.append("LOWER(COALESCE(status, '')) IN ('warning', 'dry_run')")
    elif status == "error":
        conditions.append(
            "LOWER(COALESCE(status, '')) NOT IN ('success', 'warning', 'dry_run')"
        )

    query = str(search or "").strip()
    if query:
        searchable = """
            smart_norm(CONCAT_WS(
                ' ',
                user_full_name,
                username,
                action,
                object_type,
                object_name,
                details
            )) LIKE ('%' || smart_norm(?) || '%')
        """
        params.append(query)
        label_action_keys = [
            key
            for key, label in ACTION_NAMES.items()
            if _smart_norm(query) in _smart_norm(label)
        ]
        if label_action_keys:
            placeholders = ", ".join("?" for _ in label_action_keys)
            searchable = f"({searchable} OR action IN ({placeholders}))"
            params.extend(label_action_keys)
        conditions.append(searchable)

    return (" WHERE " + " AND ".join(conditions)) if conditions else "", params


def _operation_timestamp_parts(value: object) -> tuple[str, str]:
    """Return a compact, stable timestamp representation for dashboard cards."""
    raw_value = str(value or "").replace("T", " ")
    if len(raw_value) >= 19 and raw_value[10:11] == " ":
        return raw_value[:10], raw_value[11:19]
    return raw_value, ""


def normalize_operation_row(row: dict) -> dict:
    row = dict(row)
    for field in ("details", "response", "comment"):
        row[field] = redact_audit_text(row.get(field) or "")
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

    details = redact_audit_text(row.get("details") or "")

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
        details = redact_audit_text(row.get("response") or "—")

    status = row.get("status") or "success"
    status_name = operation_status_name(status)
    status_tone = operation_status_tone(status)
    created_date, created_time = _operation_timestamp_parts(row.get("created_at"))

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
        "created_date": created_date,
        "created_time": created_time,
    }


def get_operations(
    *,
    date_from: date | datetime | str | None = None,
    date_to: date | datetime | str | None = None,
    user_id: int | None = None,
    action: str | None = None,
    object_type: str | None = None,
    status: str | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
    sort_order: str = "desc",
) -> list[dict]:
    where_sql, params = _build_operation_filters(
        date_from=date_from,
        date_to=date_to,
        user_id=user_id,
        action=action,
        object_type=object_type,
        status=status,
        search=search,
    )
    safe_limit = max(1, min(int(limit), 1000))
    safe_offset = max(0, int(offset))
    direction = "ASC" if str(sort_order).lower() == "asc" else "DESC"

    with db() as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM operation_log
            {where_sql}
            ORDER BY created_at {direction}, id {direction}
            LIMIT ?
            OFFSET ?
            """,
            (*params, safe_limit, safe_offset),
        ).fetchall()

        return [normalize_operation_row(dict(row)) for row in rows]


def count_operations(
    *,
    date_from: date | datetime | str | None = None,
    date_to: date | datetime | str | None = None,
    user_id: int | None = None,
    action: str | None = None,
    object_type: str | None = None,
    status: str | None = None,
    search: str | None = None,
) -> int:
    where_sql, params = _build_operation_filters(
        date_from=date_from,
        date_to=date_to,
        user_id=user_id,
        action=action,
        object_type=object_type,
        status=status,
        search=search,
    )
    with db() as conn:
        row = conn.execute(
            f"SELECT COUNT(*) FROM operation_log {where_sql}",
            params,
        ).fetchone()
    return int(row[0] if row else 0)


def get_operation_actions() -> list[dict]:
    """Return actions that actually occur in the journal."""
    with db() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT action
            FROM operation_log
            WHERE COALESCE(action, '') <> ''
            ORDER BY action
            """
        ).fetchall()
    items = [
        {"value": str(row[0]), "label": ACTION_NAMES.get(str(row[0]), str(row[0]))}
        for row in rows
    ]
    return sorted(items, key=lambda item: item["label"].casefold())


def get_last_operations(limit: int = 500) -> list[dict]:
    return get_operations(limit=limit, sort_order="desc")


def get_recent_operations(limit: int = 5) -> list[dict]:
    return get_last_operations(limit)
