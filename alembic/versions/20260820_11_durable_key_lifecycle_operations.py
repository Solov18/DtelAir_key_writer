"""Add durable key lifecycle operation and step tables.

Revision ID: 20260820_11
Revises: 20260820_10
"""

from alembic import op
import sqlalchemy as sa


revision = "20260820_11"
down_revision = "20260820_10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "key_lifecycle_operations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("operation_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column(
            "old_key_id", sa.Integer(),
            sa.ForeignKey("keys.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column(
            "new_key_id", sa.Integer(),
            sa.ForeignKey("keys.id", ondelete="RESTRICT"),
        ),
        sa.Column("reason", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("final_old_status", sa.Text(), nullable=False, server_default=sa.text("'free'")),
        sa.Column(
            "employee_assignment_status", sa.Text(), nullable=False,
            server_default=sa.text("'inactive'"),
        ),
        sa.Column("source_panel_ids", sa.Text(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("assignment_snapshot", sa.Text(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "operation_type IN ('release', 'replace')",
            name="ck_key_lifecycle_operation_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'deleting', 'writing', 'partial', 'error', 'completed')",
            name="ck_key_lifecycle_operation_status",
        ),
    )
    op.create_index(
        "idx_key_lifecycle_operations_resume",
        "key_lifecycle_operations",
        ["old_key_id", "new_key_id", "operation_type", "status"],
    )

    op.create_table(
        "key_lifecycle_steps",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "operation_id", sa.Integer(),
            sa.ForeignKey("key_lifecycle_operations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "panel_id", sa.Integer(),
            sa.ForeignKey("panels.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column("phase", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_status", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("result_payload", sa.Text(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "phase IN ('delete_old', 'write_new')",
            name="ck_key_lifecycle_step_phase",
        ),
        sa.CheckConstraint(
            "state IN ('pending', 'running', 'success', 'error')",
            name="ck_key_lifecycle_step_state",
        ),
        sa.UniqueConstraint(
            "operation_id", "panel_id", "phase",
            name="uq_key_lifecycle_step",
        ),
    )
    op.create_index(
        "idx_key_lifecycle_steps_pending",
        "key_lifecycle_steps",
        ["operation_id", "phase", "state"],
    )


def downgrade() -> None:
    op.drop_index("idx_key_lifecycle_steps_pending", table_name="key_lifecycle_steps")
    op.drop_table("key_lifecycle_steps")
    op.drop_index(
        "idx_key_lifecycle_operations_resume",
        table_name="key_lifecycle_operations",
    )
    op.drop_table("key_lifecycle_operations")
