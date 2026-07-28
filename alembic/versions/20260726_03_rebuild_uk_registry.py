"""Rebuild the management-company registry around panels and issued keys.

Revision ID: 20260726_03
Revises: 20260726_02
Create Date: 2026-07-26
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260726_03"
down_revision: str | None = "20260726_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "uk_groups",
        sa.Column("actual_address", sa.Text(), server_default=sa.text("''")),
    )
    op.add_column(
        "uk_groups",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.add_column(
        "uk_groups",
        sa.Column("archived_at", sa.DateTime(timezone=True)),
    )
    op.alter_column(
        "uk_groups",
        "updated_at",
        existing_type=sa.Text(),
        server_default=None,
    )
    op.alter_column(
        "uk_groups",
        "updated_at",
        existing_type=sa.Text(),
        type_=sa.DateTime(timezone=True),
        existing_nullable=True,
        postgresql_using=(
            "COALESCE(NULLIF(BTRIM(updated_at), '')::timestamptz, CURRENT_TIMESTAMP)"
        ),
    )
    op.alter_column(
        "uk_groups",
        "updated_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )

    op.create_table(
        "uk_panel_links",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("uk_group_id", sa.Integer(), nullable=False),
        sa.Column("panel_id", sa.Integer(), nullable=False),
        sa.Column("apartment", sa.Text(), nullable=False),
        sa.Column("comment", sa.Text(), server_default=sa.text("''")),
        sa.Column(
            "active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Text(), server_default=sa.text("''")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("detached_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["panel_id"],
            ["panels.id"],
            name="fk_uk_panel_links_panel_id_panels",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["uk_group_id"],
            ["uk_groups.id"],
            name="fk_uk_panel_links_uk_group_id_uk_groups",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_uk_panel_links_group_panel_active",
        "uk_panel_links",
        ["uk_group_id", "panel_id"],
        unique=True,
        postgresql_where=sa.text("active IS TRUE"),
    )
    op.create_index(
        "uq_uk_panel_links_panel_active",
        "uk_panel_links",
        ["panel_id"],
        unique=True,
        postgresql_where=sa.text("active IS TRUE"),
    )
    op.create_index(
        "idx_uk_panel_links_group",
        "uk_panel_links",
        ["uk_group_id", "active"],
    )

    op.create_table(
        "uk_key_issues",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("uk_group_id", sa.Integer(), nullable=False),
        sa.Column("key_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("comment", sa.Text(), server_default=sa.text("''")),
        sa.Column("issued_by", sa.Text(), server_default=sa.text("''")),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("released_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'active', 'released', 'archived')",
            name="ck_uk_key_issues_status",
        ),
        sa.ForeignKeyConstraint(
            ["key_id"],
            ["keys.id"],
            name="fk_uk_key_issues_key_id_keys",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["uk_group_id"],
            ["uk_groups.id"],
            name="fk_uk_key_issues_uk_group_id_uk_groups",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_uk_key_issues_key_active",
        "uk_key_issues",
        ["key_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'active')"),
    )
    op.create_index(
        "idx_uk_key_issues_group",
        "uk_key_issues",
        ["uk_group_id", "status"],
    )

    op.create_table(
        "uk_key_programmings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("issue_id", sa.Integer(), nullable=False),
        sa.Column("panel_link_id", sa.Integer(), nullable=False),
        sa.Column("apartment", sa.Text(), nullable=False),
        sa.Column(
            "is_primary",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Text(),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("last_error", sa.Text(), server_default=sa.text("''")),
        sa.Column("programmed_at", sa.DateTime(timezone=True)),
        sa.Column("removed_at", sa.DateTime(timezone=True)),
        sa.Column("unlinked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'success', 'error', 'dry_run', 'unlinked', 'removed')",
            name="ck_uk_key_programmings_status",
        ),
        sa.ForeignKeyConstraint(
            ["issue_id"],
            ["uk_key_issues.id"],
            name="fk_uk_key_programmings_issue_id_uk_key_issues",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["panel_link_id"],
            ["uk_panel_links.id"],
            name="fk_uk_key_programmings_panel_link_id_uk_panel_links",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_uk_key_programmings_issue_panel_active",
        "uk_key_programmings",
        ["issue_id", "panel_link_id"],
        unique=True,
        postgresql_where=sa.text("active IS TRUE"),
    )
    op.create_index(
        "uq_uk_key_programmings_primary_active",
        "uk_key_programmings",
        ["issue_id"],
        unique=True,
        postgresql_where=sa.text("active IS TRUE AND is_primary IS TRUE"),
    )
    op.create_index(
        "idx_uk_key_programmings_issue",
        "uk_key_programmings",
        ["issue_id", "active"],
    )

    op.create_table(
        "uk_crm_operations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("programming_id", sa.Integer(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column(
            "attempt_number",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("safe_response", sa.Text(), server_default=sa.text("''")),
        sa.Column("requested_by", sa.Text(), server_default=sa.text("''")),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "operation IN ('add', 'remove')",
            name="ck_uk_crm_operations_operation",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'success', 'error', 'dry_run')",
            name="ck_uk_crm_operations_status",
        ),
        sa.ForeignKeyConstraint(
            ["programming_id"],
            ["uk_key_programmings.id"],
            name="fk_uk_crm_operations_programming_id_uk_key_programmings",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_uk_crm_operations_idempotency_key",
        ),
    )
    op.create_index(
        "idx_uk_crm_operations_programming",
        "uk_crm_operations",
        ["programming_id", sa.text("started_at DESC")],
    )

    op.drop_table("uk_integrations")
    op.drop_table("uk_notification_drafts")
    op.drop_table("uk_group_keys")
    op.drop_table("uk_group_panels")

    for column_name in (
        "contract_number",
        "cooperation_status",
        "account_manager",
        "next_contact_at",
        "cooperation_note",
    ):
        op.drop_column("uk_groups", column_name)


def downgrade() -> None:
    op.add_column(
        "uk_groups",
        sa.Column("contract_number", sa.Text(), server_default=sa.text("''")),
    )
    op.add_column(
        "uk_groups",
        sa.Column(
            "cooperation_status",
            sa.Text(),
            server_default=sa.text("'potential'"),
            nullable=False,
        ),
    )
    op.add_column(
        "uk_groups",
        sa.Column("account_manager", sa.Text(), server_default=sa.text("''")),
    )
    op.add_column(
        "uk_groups",
        sa.Column("next_contact_at", sa.Text(), server_default=sa.text("''")),
    )
    op.add_column(
        "uk_groups",
        sa.Column("cooperation_note", sa.Text(), server_default=sa.text("''")),
    )

    op.create_table(
        "uk_group_panels",
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("panel_id", sa.Integer(), nullable=False),
        sa.UniqueConstraint(
            "group_id",
            "panel_id",
            name="uq_uk_group_panels_group_panel",
        ),
    )
    op.execute(
        """
        INSERT INTO uk_group_panels(group_id, panel_id)
        SELECT uk_group_id, panel_id
        FROM uk_panel_links
        WHERE active IS TRUE
        ON CONFLICT (group_id, panel_id) DO NOTHING
        """
    )

    op.create_table(
        "uk_group_keys",
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("key_id", sa.Integer(), nullable=False),
        sa.UniqueConstraint(
            "group_id",
            "key_id",
            name="uq_uk_group_keys_group_key",
        ),
    )
    op.execute(
        """
        INSERT INTO uk_group_keys(group_id, key_id)
        SELECT uk_group_id, key_id
        FROM uk_key_issues
        WHERE status IN ('pending', 'active')
        ON CONFLICT (group_id, key_id) DO NOTHING
        """
    )

    op.create_table(
        "uk_notification_drafts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "category",
            sa.Text(),
            server_default=sa.text("'announcement'"),
            nullable=False,
        ),
        sa.Column(
            "channel",
            sa.Text(),
            server_default=sa.text("'dtel'"),
            nullable=False,
        ),
        sa.Column(
            "audience",
            sa.Text(),
            server_default=sa.text("'all'"),
            nullable=False,
        ),
        sa.Column("audience_details", sa.Text(), server_default=sa.text("''")),
        sa.Column("created_by", sa.Text(), server_default=sa.text("''")),
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
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["uk_groups.id"],
            name="fk_uk_notification_drafts_group_id_uk_groups",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_uk_notification_drafts_group",
        "uk_notification_drafts",
        ["group_id", sa.text("created_at DESC")],
    )

    op.create_table(
        "uk_integrations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("service_name", sa.Text(), nullable=False),
        sa.Column(
            "integration_type",
            sa.Text(),
            server_default=sa.text("'api'"),
            nullable=False,
        ),
        sa.Column("base_url", sa.Text(), server_default=sa.text("''")),
        sa.Column("login", sa.Text(), server_default=sa.text("''")),
        sa.Column(
            "auth_type",
            sa.Text(),
            server_default=sa.text("'not_selected'"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Text(),
            server_default=sa.text("'planned'"),
            nullable=False,
        ),
        sa.Column(
            "enabled",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("note", sa.Text(), server_default=sa.text("''")),
        sa.Column("last_sync_at", sa.Text(), server_default=sa.text("''")),
        sa.Column("last_error", sa.Text(), server_default=sa.text("''")),
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
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["uk_groups.id"],
            name="fk_uk_integrations_group_id_uk_groups",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_uk_integrations_group_service_ci",
        "uk_integrations",
        ["group_id", sa.text("lower(service_name)")],
        unique=True,
    )
    op.create_index(
        "idx_uk_integrations_group",
        "uk_integrations",
        ["group_id", "status", "service_name"],
    )

    op.drop_index(
        "idx_uk_crm_operations_programming",
        table_name="uk_crm_operations",
    )
    op.drop_table("uk_crm_operations")
    op.drop_index(
        "idx_uk_key_programmings_issue",
        table_name="uk_key_programmings",
    )
    op.drop_index(
        "uq_uk_key_programmings_primary_active",
        table_name="uk_key_programmings",
    )
    op.drop_index(
        "uq_uk_key_programmings_issue_panel_active",
        table_name="uk_key_programmings",
    )
    op.drop_table("uk_key_programmings")
    op.drop_index("idx_uk_key_issues_group", table_name="uk_key_issues")
    op.drop_index("uq_uk_key_issues_key_active", table_name="uk_key_issues")
    op.drop_table("uk_key_issues")
    op.drop_index("idx_uk_panel_links_group", table_name="uk_panel_links")
    op.drop_index("uq_uk_panel_links_panel_active", table_name="uk_panel_links")
    op.drop_index(
        "uq_uk_panel_links_group_panel_active",
        table_name="uk_panel_links",
    )
    op.drop_table("uk_panel_links")

    op.alter_column(
        "uk_groups",
        "updated_at",
        existing_type=sa.DateTime(timezone=True),
        server_default=None,
    )
    op.alter_column(
        "uk_groups",
        "updated_at",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.Text(),
        existing_nullable=False,
        postgresql_using="COALESCE(updated_at::text, '')",
    )
    op.alter_column(
        "uk_groups",
        "updated_at",
        existing_type=sa.Text(),
        nullable=True,
        server_default=sa.text("''"),
    )
    op.drop_column("uk_groups", "archived_at")
    op.drop_column("uk_groups", "created_at")
    op.drop_column("uk_groups", "actual_address")
