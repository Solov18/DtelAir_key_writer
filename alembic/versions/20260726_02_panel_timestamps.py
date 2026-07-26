"""Use timezone-aware timestamps for panel status checks.

Revision ID: 20260726_02
Revises: 20260724_01
Create Date: 2026-07-26
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260726_02"
down_revision: str | None = "20260724_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION smart_norm(value TEXT)
        RETURNS TEXT
        LANGUAGE SQL
        IMMUTABLE
        PARALLEL SAFE
        AS $$
            SELECT REGEXP_REPLACE(
                TRANSLATE(LOWER(COALESCE(value, '')), 'ё', 'е'),
                '[^0-9a-zа-я]+',
                '',
                'g'
            )
        $$
        """
    )
    for column_name in ("last_checked_at", "last_online_at"):
        op.alter_column(
            "panels",
            column_name,
            existing_type=sa.Text(),
            server_default=None,
        )
        op.alter_column(
            "panels",
            column_name,
            existing_type=sa.Text(),
            type_=sa.DateTime(timezone=True),
            existing_nullable=True,
            postgresql_using=(
                f"NULLIF(BTRIM({column_name}), '')::timestamptz"
            ),
        )


def downgrade() -> None:
    for column_name in ("last_checked_at", "last_online_at"):
        op.alter_column(
            "panels",
            column_name,
            existing_type=sa.DateTime(timezone=True),
            type_=sa.Text(),
            existing_nullable=True,
            postgresql_using=f"COALESCE({column_name}::text, '')",
        )
        op.alter_column(
            "panels",
            column_name,
            existing_type=sa.Text(),
            server_default=sa.text("''"),
        )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION smart_norm(value TEXT)
        RETURNS TEXT
        LANGUAGE SQL
        IMMUTABLE
        PARALLEL SAFE
        AS $$
            SELECT BTRIM(
                REGEXP_REPLACE(
                    TRANSLATE(LOWER(COALESCE(value, '')), 'ё', 'е'),
                    '[^0-9a-zа-я]+',
                    ' ',
                    'g'
                )
            )
        $$
        """
    )
