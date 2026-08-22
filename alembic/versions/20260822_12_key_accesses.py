"""Add explicit multi-address key accesses.

Revision ID: 20260822_12
Revises: 20260820_11
"""

from alembic import op
import sqlalchemy as sa


revision = "20260822_12"
down_revision = "20260820_11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "key_accesses",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("key_id", sa.Integer(), sa.ForeignKey("keys.id", ondelete="RESTRICT"), nullable=False),
        sa.Column(
            "assignment_id", sa.Integer(),
            sa.ForeignKey("key_assignments.id", ondelete="SET NULL"),
        ),
        sa.Column("access_type", sa.Text(), nullable=False, server_default=sa.text("'resident'")),
        sa.Column("address", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("apartment", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("owner_name", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("active", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("is_primary", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("source", sa.Text(), nullable=False, server_default=sa.text("'assignment'")),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("released_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("note", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.CheckConstraint("access_type IN ('resident', 'service')", name="ck_key_accesses_type"),
        sa.CheckConstraint("active IN (0, 1)", name="ck_key_accesses_active"),
        sa.CheckConstraint("is_primary IN (0, 1)", name="ck_key_accesses_primary"),
    )
    op.create_index("idx_key_accesses_key_active", "key_accesses", ["key_id", "active"])
    op.create_index(
        "idx_key_accesses_address_active", "key_accesses",
        ["address", "apartment", "active"],
    )
    op.create_index(
        "uq_key_accesses_active_identity", "key_accesses",
        ["key_id", "access_type", "address", "apartment"],
        unique=True,
        postgresql_where=sa.text("active = 1"),
    )

    op.add_column("key_panel_states", sa.Column("access_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_key_panel_states_access_id", "key_panel_states", "key_accesses",
        ["access_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index(
        "idx_key_panel_states_access", "key_panel_states", ["access_id", "state"],
    )

    # Only current active assignments prove an active access.  Historical
    # operation_log rows are deliberately ignored.
    op.execute(
        """
        INSERT INTO key_accesses(
            key_id, assignment_id, access_type, address, apartment,
            owner_name, active, is_primary, source, assigned_at, created_by, note
        )
        SELECT
            ka.key_id,
            ka.id,
            CASE WHEN ka.assignment_type = 'resident' THEN 'resident' ELSE 'service' END,
            COALESCE(ka.address, ''),
            COALESCE(ka.apartment, ''),
            COALESCE(NULLIF(ka.note, ''), e.full_name, ug.name, ''),
            1,
            1,
            'assignment_backfill',
            COALESCE(NULLIF(ka.assigned_at, '')::timestamptz, CURRENT_TIMESTAMP),
            COALESCE(ka.assigned_by, ''),
            COALESCE(ka.note, '')
        FROM key_assignments ka
        JOIN keys k ON k.id = ka.key_id
        LEFT JOIN employees e ON e.id = ka.employee_id
        LEFT JOIN uk_groups ug ON ug.id = ka.uk_group_id
        WHERE ka.active = 1
          AND (k.is_used = 1 OR k.status <> 'free')
        ON CONFLICT DO NOTHING
        """
    )
    # Link a panel only where both current panel state and address/flat context
    # agree. Ambiguous legacy rows remain NULL and require reconciliation.
    op.execute(
        """
        UPDATE key_panel_states kps
        SET access_id = ka.id
        FROM key_accesses ka, panels p
        WHERE kps.panel_id = p.id
          AND kps.key_id = ka.key_id
          AND kps.state IN ('active', 'pending_delete')
          AND ka.active = 1
          AND LOWER(BTRIM(ka.address)) = LOWER(BTRIM(COALESCE(p.address, '')))
          AND (
              BTRIM(ka.apartment) = ''
              OR BTRIM(ka.apartment) = BTRIM(COALESCE(kps.flat_num, ''))
          )
        """
    )

    op.drop_constraint(
        "ck_key_lifecycle_operation_type", "key_lifecycle_operations", type_="check",
    )
    op.create_check_constraint(
        "ck_key_lifecycle_operation_type", "key_lifecycle_operations",
        "operation_type IN ('release', 'reassign', 'replace', 'add_access')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_key_lifecycle_operation_type", "key_lifecycle_operations", type_="check",
    )
    op.create_check_constraint(
        "ck_key_lifecycle_operation_type", "key_lifecycle_operations",
        "operation_type IN ('release', 'replace')",
    )
    op.drop_index("idx_key_panel_states_access", table_name="key_panel_states")
    op.drop_constraint(
        "fk_key_panel_states_access_id", "key_panel_states", type_="foreignkey",
    )
    op.drop_column("key_panel_states", "access_id")
    op.drop_index("uq_key_accesses_active_identity", table_name="key_accesses")
    op.drop_index("idx_key_accesses_address_active", table_name="key_accesses")
    op.drop_index("idx_key_accesses_key_active", table_name="key_accesses")
    op.drop_table("key_accesses")
