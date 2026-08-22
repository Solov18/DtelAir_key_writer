"""Add authoritative key to panel lifecycle state.

Revision ID: 20260820_10
Revises: 20260814_09
"""

from alembic import op
import sqlalchemy as sa


revision = "20260820_10"
down_revision = "20260814_09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "key_panel_states",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("key_id", sa.Integer(), sa.ForeignKey("keys.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("panel_id", sa.Integer(), sa.ForeignKey("panels.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("state", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("flat_num", sa.Text(), nullable=False, server_default=sa.text("'0'")),
        sa.Column("is_inner", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("uk_group_id", sa.Integer(), sa.ForeignKey("uk_groups.id", ondelete="SET NULL")),
        sa.Column("last_operation", sa.Text(), nullable=False, server_default=sa.text("'write'")),
        sa.Column("last_status", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("removed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "state IN ('unknown', 'pending_write', 'active', 'pending_delete', 'error', 'removed')",
            name="ck_key_panel_states_state",
        ),
        sa.UniqueConstraint("key_id", "panel_id", name="uq_key_panel_states_key_panel"),
    )
    op.create_index("idx_key_panel_states_key_active", "key_panel_states", ["key_id", "state"])
    op.create_index("idx_key_panel_states_panel_active", "key_panel_states", ["panel_id", "state"])

    # operation_log is audit history, not proof of current external state.  A
    # legacy successful write is imported only as UNKNOWN and only when the
    # current local records still prove that the key is occupied.  A free key
    # with no active assignment therefore receives no current panel state.
    op.execute(
        """
        INSERT INTO key_panel_states(
            key_id, panel_id, state, flat_num, is_inner, uk_group_id,
            last_operation, last_status, last_error, confirmed_at
        )
        SELECT
            latest.key_id,
            latest.panel_id,
            'unknown',
            COALESCE(NULLIF(latest.flat_num, ''), '0'),
            CASE WHEN COALESCE(latest.uk_group_id, 0) > 0 THEN 0 ELSE 1 END,
            latest.uk_group_id,
            'write',
            COALESCE(latest.status, ''),
            'Требуется сверка: связь восстановлена только из исторического журнала',
            NULL
        FROM (
            SELECT DISTINCT ON (key_id, panel_id) *
            FROM operation_log
            WHERE key_id IS NOT NULL
              AND panel_id IS NOT NULL
              AND UPPER(COALESCE(status, '')) IN
                  ('SUCCESS', 'ALREADY_EXISTS', 'ALREADY_ON_PANEL')
            ORDER BY key_id, panel_id, id DESC
        ) AS latest
        JOIN keys legacy_key ON legacy_key.id = latest.key_id
        WHERE LOWER(COALESCE(latest.action, '') || ' ' || COALESCE(latest.mode, ''))
              !~ '(remove|delete|unlink)'
          AND (
              COALESCE(legacy_key.is_used, 0) = 1
              OR LOWER(COALESCE(legacy_key.status, '')) NOT IN ('', 'free')
              OR EXISTS (
                  SELECT 1 FROM key_assignments a
                  WHERE a.key_id = legacy_key.id AND a.active = 1
              )
              OR EXISTS (
                  SELECT 1 FROM employee_keys ek
                  WHERE ek.key_id = legacy_key.id AND ek.status = 'active'
              )
              OR EXISTS (
                  SELECT 1 FROM uk_key_issues ui
                  WHERE ui.key_id = legacy_key.id AND ui.status IN ('pending', 'active')
              )
          )
        ON CONFLICT (key_id, panel_id) DO NOTHING
        """
    )

    # UK accounting has its own durable programming table. Seed confirmed
    # active relations from it as well, including installations created before
    # operation_log acquired key/panel identifiers.
    op.execute(
        """
        INSERT INTO key_panel_states(
            key_id, panel_id, state, flat_num, is_inner, uk_group_id,
            last_operation, last_status, last_error, confirmed_at
        )
        SELECT
            issue.key_id,
            link.panel_id,
            'active',
            COALESCE(NULLIF(programming.apartment, ''), '0'),
            0,
            issue.uk_group_id,
            'write',
            UPPER(COALESCE(programming.status, 'SUCCESS')),
            '',
            COALESCE(programming.programmed_at, programming.updated_at, CURRENT_TIMESTAMP)
        FROM uk_key_programmings programming
        JOIN uk_key_issues issue ON issue.id = programming.issue_id
        JOIN uk_panel_links link ON link.id = programming.panel_link_id
        WHERE programming.active IS TRUE
          AND UPPER(COALESCE(programming.status, 'SUCCESS')) IN
              ('SUCCESS', 'ALREADY_EXISTS', 'ALREADY_ON_PANEL')
        ON CONFLICT (key_id, panel_id) DO UPDATE SET
            state = 'active',
            flat_num = EXCLUDED.flat_num,
            uk_group_id = EXCLUDED.uk_group_id,
            last_operation = 'write',
            last_status = EXCLUDED.last_status,
            last_error = '',
            confirmed_at = EXCLUDED.confirmed_at,
            removed_at = NULL,
            updated_at = CURRENT_TIMESTAMP
        """
    )


def downgrade() -> None:
    op.drop_index("idx_key_panel_states_panel_active", table_name="key_panel_states")
    op.drop_index("idx_key_panel_states_key_active", table_name="key_panel_states")
    op.drop_table("key_panel_states")
