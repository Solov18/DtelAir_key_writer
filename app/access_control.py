PERMISSION_LABELS = {
    "view": "Просмотр",
    "write_keys": "Запись ключей",
    "manage_keys": "Управление ключами",
    "manage_panels": "Управление панелями",
    "manage_uk": "Управление УК",
    "manage_employees": "Управление сотрудниками",
    "view_logs": "Просмотр журналов",
    "manage_users": "Управление пользователями",
    "manage_settings": "Системные настройки",
}

SYSTEM_ROLE_LABELS = {
    "admin": "Администратор",
    "operator": "Оператор",
    "viewer": "Наблюдатель",
}


def normalize_role(role: str) -> str:
    return str(role or "viewer")


def role_label(role: str) -> str:
    return SYSTEM_ROLE_LABELS.get(normalize_role(role), normalize_role(role))


def has_permission(user: dict | None, permission: str) -> bool:
    if not user or not int(user.get("active", 1)):
        return False
    return permission in set(user.get("permissions") or [])
