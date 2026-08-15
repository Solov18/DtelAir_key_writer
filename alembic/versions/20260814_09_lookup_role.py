"""Add the lookup-only role and universal-search permission.

Revision ID: 20260814_09
Revises: 20260814_08
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260814_09"
down_revision: str | None = "20260814_08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO permissions(code, name, description)
        VALUES (
            'use_universal_search',
            'Универсальный поиск',
            'Поиск адресов, квартир, ключей, назначений и доступной истории'
        )
        ON CONFLICT (code) DO UPDATE
        SET name = EXCLUDED.name,
            description = EXCLUDED.description
        """
    )
    op.execute(
        """
        INSERT INTO roles(code, name, description, is_system)
        VALUES (
            'lookup',
            'Справочная',
            'Только универсальный поиск без доступа к изменениям и реестрам.',
            true
        )
        ON CONFLICT (code) DO UPDATE
        SET name = EXCLUDED.name,
            description = EXCLUDED.description,
            is_system = true
        """
    )

    # Preserve universal-search access for every existing role that already
    # had general read access, including custom roles.
    op.execute(
        """
        INSERT INTO role_permissions(role_id, permission_id)
        SELECT DISTINCT existing.role_id, search_permission.id
        FROM role_permissions AS existing
        JOIN permissions AS current_permission
          ON current_permission.id = existing.permission_id
         AND current_permission.code = 'view'
        CROSS JOIN permissions AS search_permission
        WHERE search_permission.code = 'use_universal_search'
        ON CONFLICT DO NOTHING
        """
    )

    # The reserved lookup role must remain strictly search-only.
    op.execute(
        """
        DELETE FROM role_permissions
        WHERE role_id = (SELECT id FROM roles WHERE code = 'lookup')
        """
    )
    op.execute(
        """
        INSERT INTO role_permissions(role_id, permission_id)
        SELECT role_row.id, permission_row.id
        FROM roles AS role_row
        CROSS JOIN permissions AS permission_row
        WHERE role_row.code = 'lookup'
          AND permission_row.code = 'use_universal_search'
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    # Keep users valid under the users.role_id RESTRICT foreign key.
    op.execute(
        """
        UPDATE users
        SET role_id = (SELECT id FROM roles WHERE code = 'viewer')
        WHERE role_id = (SELECT id FROM roles WHERE code = 'lookup')
        """
    )
    op.execute("DELETE FROM roles WHERE code = 'lookup'")
    op.execute("DELETE FROM permissions WHERE code = 'use_universal_search'")
