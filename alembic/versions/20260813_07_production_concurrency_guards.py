"""Add production uniqueness guards for concurrent requests.

Revision ID: 20260813_07
Revises: 20260730_06
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260813_07"
down_revision: str | None = "20260730_06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # These indexes deliberately fail the migration if legacy duplicates exist.
    # The deployment runbook contains read-only preflight queries so an operator
    # can resolve them explicitly instead of silently deleting business data.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_keys_hex_nonempty_ci
        ON keys (UPPER(hex_value))
        WHERE BTRIM(hex_value) <> ''
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_users_login_ci
        ON users (LOWER(login))
        """
    )


def downgrade() -> None:
    op.drop_index("uq_users_login_ci", table_name="users")
    op.drop_index("uq_keys_hex_nonempty_ci", table_name="keys")
