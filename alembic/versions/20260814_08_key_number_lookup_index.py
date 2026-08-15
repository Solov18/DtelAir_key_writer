"""Add a normalized lookup index for numeric key numbers.

Revision ID: 20260814_08
Revises: 20260813_07
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260814_08"
down_revision: str | None = "20260813_07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The stored number remains TEXT.  The normalized value exists only in
    # this partial expression index and in lookup predicates.
    op.execute(
        """
        CREATE INDEX idx_keys_number_normalized_type
        ON keys (
            (COALESCE(NULLIF(LTRIM(BTRIM(number), '0'), ''), '0')),
            key_type_id
        )
        WHERE BTRIM(number) ~ '^[0-9]+$'
        """
    )


def downgrade() -> None:
    op.drop_index("idx_keys_number_normalized_type", table_name="keys")
