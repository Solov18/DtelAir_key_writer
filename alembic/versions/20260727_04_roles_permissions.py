"""Add database-backed roles and permissions.

Revision ID: 20260727_04
Revises: 20260726_03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260727_04"
down_revision: str | None = "20260726_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PERMISSIONS = (
    (1, "view", "Просмотр", "Просмотр доступных разделов и карточек"),
    (2, "write_keys", "Запись ключей", "Отправка ключей в CRM"),
    (3, "manage_keys", "Управление ключами", "Реестр, типы и состояния ключей"),
    (4, "manage_panels", "Управление панелями", "Панели, импорт и действия устройств"),
    (5, "manage_uk", "Управление УК", "Карточки УК, панели и служебные ключи"),
    (6, "manage_employees", "Управление сотрудниками", "Карточки и ключи сотрудников"),
    (7, "view_logs", "Просмотр журналов", "Журнал операций и безопасности"),
    (8, "manage_users", "Управление пользователями", "Учётные записи и назначение ролей"),
    (9, "manage_settings", "Системные настройки", "Настройки системы и управление ролями"),
)

ROLES = (
    (
        1,
        "admin",
        "Администратор",
        "Полный доступ и управление безопасностью системы.",
    ),
    (
        2,
        "operator",
        "Оператор",
        "Работа с реестрами, панелями и записью ключей.",
    ),
    (
        3,
        "viewer",
        "Наблюдатель",
        "Просмотр данных и журналов без изменений.",
    ),
)

ROLE_PERMISSION_IDS = {
    1: tuple(range(1, 10)),
    2: (1, 2, 3, 4, 5, 6, 7),
    3: (1, 7),
}


def upgrade() -> None:
    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("is_system", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.Text(),
            server_default=sa.text("CAST(CURRENT_TIMESTAMP AS TEXT)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.Text(),
            server_default=sa.text("CAST(CURRENT_TIMESTAMP AS TEXT)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_roles_code"),
    )
    op.create_index(
        "uq_roles_name_ci",
        "roles",
        [sa.text("lower(name)")],
        unique=True,
    )
    op.create_table(
        "permissions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_permissions_code"),
    )
    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column("permission_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["permission_id"], ["permissions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("role_id", "permission_id"),
    )

    role_table = sa.table(
        "roles",
        sa.column("id", sa.Integer()),
        sa.column("code", sa.Text()),
        sa.column("name", sa.Text()),
        sa.column("description", sa.Text()),
        sa.column("is_system", sa.Boolean()),
    )
    permission_table = sa.table(
        "permissions",
        sa.column("id", sa.Integer()),
        sa.column("code", sa.Text()),
        sa.column("name", sa.Text()),
        sa.column("description", sa.Text()),
    )
    role_permission_table = sa.table(
        "role_permissions",
        sa.column("role_id", sa.Integer()),
        sa.column("permission_id", sa.Integer()),
    )
    op.bulk_insert(
        role_table,
        [
            {
                "id": role_id,
                "code": code,
                "name": name,
                "description": description,
                "is_system": True,
            }
            for role_id, code, name, description in ROLES
        ],
    )
    op.bulk_insert(
        permission_table,
        [
            {"id": item_id, "code": code, "name": name, "description": description}
            for item_id, code, name, description in PERMISSIONS
        ],
    )
    op.bulk_insert(
        role_permission_table,
        [
            {"role_id": role_id, "permission_id": permission_id}
            for role_id, permission_ids in ROLE_PERMISSION_IDS.items()
            for permission_id in permission_ids
        ],
    )
    op.execute(
        "SELECT setval(pg_get_serial_sequence('roles', 'id'), "
        "(SELECT MAX(id) FROM roles), true)"
    )
    op.execute(
        "SELECT setval(pg_get_serial_sequence('permissions', 'id'), "
        "(SELECT MAX(id) FROM permissions), true)"
    )

    op.add_column("users", sa.Column("role_id", sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE users AS u
        SET role_id = COALESCE(
            (SELECT r.id FROM roles AS r WHERE r.code = u.role),
            (SELECT r.id FROM roles AS r WHERE r.code = 'viewer')
        )
        """
    )
    op.alter_column("users", "role_id", nullable=False)
    op.create_foreign_key(
        "fk_users_role_id_roles",
        "users",
        "roles",
        ["role_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_column("users", "role")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column("role", sa.Text(), server_default=sa.text("'viewer'"), nullable=True),
    )
    op.execute(
        """
        UPDATE users AS u
        SET role = COALESCE(
            (SELECT r.code FROM roles AS r WHERE r.id = u.role_id),
            'viewer'
        )
        """
    )
    op.alter_column("users", "role", nullable=False)
    op.drop_constraint("fk_users_role_id_roles", "users", type_="foreignkey")
    op.drop_column("users", "role_id")
    op.drop_table("role_permissions")
    op.drop_table("permissions")
    op.drop_index("uq_roles_name_ci", table_name="roles")
    op.drop_table("roles")
