ROLE_DEFINITIONS = {
    "admin": {
        "label": "Администратор",
        "description": "Полный доступ, настройки системы и управление пользователями.",
        "permissions": {
            "view",
            "write_keys",
            "manage_registry",
            "manage_users",
            "manage_settings",
        },
    },
    "operator": {
        "label": "Оператор",
        "description": "Поиск, работа с реестрами и запись ключей без системных настроек.",
        "permissions": {
            "view",
            "write_keys",
            "manage_registry",
        },
    },
    "viewer": {
        "label": "Наблюдатель",
        "description": "Только просмотр, поиск и учебные проверки без изменений.",
        "permissions": {"view"},
    },
}

ROLE_ORDER = ("admin", "operator", "viewer")


def normalize_role(role: str) -> str:
    return role if role in ROLE_DEFINITIONS else "viewer"


def role_label(role: str) -> str:
    return ROLE_DEFINITIONS[normalize_role(role)]["label"]


def has_permission(user: dict | None, permission: str) -> bool:
    if not user or not int(user.get("active", 1)):
        return False
    role = normalize_role(str(user.get("role") or ""))
    return permission in ROLE_DEFINITIONS[role]["permissions"]

