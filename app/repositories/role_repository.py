from __future__ import annotations

from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from app.db import db


PERMISSION_DEFINITIONS = (
    (
        "use_universal_search",
        "Универсальный поиск",
        "Поиск адресов, квартир, ключей, назначений и доступной истории",
    ),
    ("view", "Просмотр", "Просмотр доступных разделов и карточек"),
    ("write_keys", "Запись ключей", "Отправка ключей в CRM"),
    ("manage_keys", "Управление ключами", "Реестр, типы и состояния ключей"),
    ("manage_panels", "Управление панелями", "Панели, импорт и действия устройств"),
    ("manage_uk", "Управление УК", "Карточки УК, панели и служебные ключи"),
    ("manage_employees", "Управление сотрудниками", "Карточки и ключи сотрудников"),
    ("view_logs", "Просмотр журналов", "Журнал операций и безопасности"),
    ("manage_users", "Управление пользователями", "Учётные записи и назначение ролей"),
    ("manage_settings", "Системные настройки", "Настройки системы и управление ролями"),
)

SYSTEM_ROLES = (
    ("admin", "Администратор", "Полный доступ и управление безопасностью системы.", {item[0] for item in PERMISSION_DEFINITIONS}),
    ("operator", "Оператор", "Работа с реестрами, панелями и записью ключей.", {"use_universal_search", "view", "write_keys", "manage_keys", "manage_panels", "manage_uk", "manage_employees", "view_logs"}),
    ("viewer", "Наблюдатель", "Просмотр данных и журналов без изменений.", {"use_universal_search", "view", "view_logs"}),
    ("lookup", "Справочная", "Только универсальный поиск без доступа к изменениям и реестрам.", {"use_universal_search"}),
)

ADMIN_CRITICAL_PERMISSIONS = frozenset(
    {"use_universal_search", "view", "manage_users", "manage_settings"}
)


def ensure_system_roles() -> None:
    """Seed access-control rows for metadata-created test schemas."""
    with db() as conn:
        for code, name, description in PERMISSION_DEFINITIONS:
            conn.execute(
                """
                INSERT INTO permissions(code, name, description)
                VALUES (?, ?, ?)
                ON CONFLICT (code) DO NOTHING
                """,
                (code, name, description),
            )
        for code, name, description, permission_codes in SYSTEM_ROLES:
            conn.execute(
                """
                INSERT INTO roles(code, name, description, is_system)
                VALUES (?, ?, ?, true)
                ON CONFLICT (code) DO NOTHING
                """,
                (code, name, description),
            )
            role_id = conn.execute(
                "SELECT id FROM roles WHERE code = ?",
                (code,),
            ).fetchone()[0]
            existing = conn.execute(
                "SELECT COUNT(*) FROM role_permissions WHERE role_id = ?",
                (role_id,),
            ).fetchone()[0]
            if not existing:
                for permission_code in sorted(permission_codes):
                    conn.execute(
                        """
                        INSERT INTO role_permissions(role_id, permission_id)
                        SELECT ?, id FROM permissions WHERE code = ?
                        ON CONFLICT DO NOTHING
                        """,
                        (role_id, permission_code),
                    )


def get_permissions() -> list[dict]:
    with db() as conn:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT id, code, name, description FROM permissions ORDER BY id"
            )
        ]


def get_roles() -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT
                r.id,
                r.code,
                r.name,
                r.description,
                r.is_system,
                COUNT(DISTINCT u.id) AS user_count,
                COALESCE(
                    ARRAY_AGG(DISTINCT p.code) FILTER (WHERE p.code IS NOT NULL),
                    ARRAY[]::TEXT[]
                ) AS permissions
            FROM roles r
            LEFT JOIN users u ON u.role_id = r.id
            LEFT JOIN role_permissions rp ON rp.role_id = r.id
            LEFT JOIN permissions p ON p.id = rp.permission_id
            GROUP BY r.id
            ORDER BY r.is_system DESC, r.id
            """
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["permissions"] = set(item.get("permissions") or [])
        item["user_count"] = int(item.get("user_count") or 0)
        result.append(item)
    return result


def get_role(role_id: int) -> dict | None:
    return next((role for role in get_roles() if int(role["id"]) == int(role_id)), None)


def get_role_by_code(code: str) -> dict | None:
    return next((role for role in get_roles() if role["code"] == code), None)


def create_role(name: str, description: str, permission_codes: set[str]) -> int:
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("Укажите название роли")
    code = f"custom_{uuid4().hex[:12]}"
    with db() as conn:
        duplicate = conn.execute(
            "SELECT id FROM roles WHERE LOWER(name) = LOWER(?)",
            (clean_name,),
        ).fetchone()
        if duplicate:
            raise ValueError("Роль с таким названием уже существует")
        try:
            result = conn.execute(
                """
                INSERT INTO roles(code, name, description, is_system)
                VALUES (?, ?, ?, false)
                """,
                (code, clean_name, description.strip()),
            )
        except IntegrityError as error:
            raise ValueError("Роль с таким названием уже существует") from error
        role_id = int(result.lastrowid)
    set_role_permissions(role_id, permission_codes)
    return role_id


def update_role(role_id: int, name: str, description: str) -> None:
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("Укажите название роли")
    with db() as conn:
        duplicate = conn.execute(
            """
            SELECT id FROM roles
            WHERE LOWER(name) = LOWER(?) AND id <> ?
            """,
            (clean_name, role_id),
        ).fetchone()
        if duplicate:
            raise ValueError("Роль с таким названием уже существует")
        try:
            conn.execute(
                """
                UPDATE roles
                SET name = ?, description = ?, updated_at = CAST(CURRENT_TIMESTAMP AS TEXT)
                WHERE id = ?
                """,
                (clean_name, description.strip(), role_id),
            )
        except IntegrityError as error:
            raise ValueError("Роль с таким названием уже существует") from error


def set_role_permissions(role_id: int, permission_codes: set[str]) -> None:
    role = get_role(role_id)
    if not role:
        raise ValueError("Роль не найдена")
    allowed = {item["code"] for item in get_permissions()}
    selected = set(permission_codes) & allowed
    if role["code"] == "admin":
        selected |= set(ADMIN_CRITICAL_PERMISSIONS)
    elif role["code"] == "lookup":
        selected = {"use_universal_search"}
    with db() as conn:
        conn.execute("DELETE FROM role_permissions WHERE role_id = ?", (role_id,))
        for permission_code in sorted(selected):
            conn.execute(
                """
                INSERT INTO role_permissions(role_id, permission_id)
                SELECT ?, id FROM permissions WHERE code = ?
                """,
                (role_id, permission_code),
            )
        conn.execute(
            "UPDATE roles SET updated_at = CAST(CURRENT_TIMESTAMP AS TEXT) WHERE id = ?",
            (role_id,),
        )


def delete_role(role_id: int) -> None:
    role = get_role(role_id)
    if not role:
        raise ValueError("Роль не найдена")
    if role["is_system"]:
        raise ValueError("Системную роль удалить нельзя")
    if role["user_count"]:
        raise ValueError("Сначала назначьте пользователям другую роль")
    with db() as conn:
        conn.execute("DELETE FROM roles WHERE id = ?", (role_id,))


def get_users_for_role(role_id: int) -> list[dict]:
    with db() as conn:
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT id, full_name, login, active, last_login
                FROM users
                WHERE role_id = ?
                ORDER BY active DESC, full_name
                """,
                (role_id,),
            )
        ]
