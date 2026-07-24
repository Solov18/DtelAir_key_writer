"""Initial PostgreSQL schema matching the legacy SQLite structure.

Revision ID: 20260724_01
Revises:
Create Date: 2026-07-24
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260724_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_now_text = sa.text("CAST(CURRENT_TIMESTAMP AS TEXT)")


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION smart_norm(value TEXT)
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

    op.create_table(
        "key_types",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "color",
            sa.Text(),
            server_default=sa.text("'#2A9DF4'"),
            nullable=False,
        ),
        sa.Column("note", sa.Text(), server_default=sa.text("''")),
        sa.Column("enabled", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.Text(), server_default=_now_text, nullable=False),
        sa.Column("updated_at", sa.Text(), server_default=_now_text, nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_key_types_name_ci",
        "key_types",
        [sa.text("lower(name)")],
        unique=True,
    )

    op.create_table(
        "employees",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), server_default=sa.text("''")),
        sa.Column("enabled", sa.Integer(), server_default=sa.text("1")),
        sa.Column("created_at", sa.Text(), server_default=_now_text),
        sa.Column("updated_at", sa.Text(), server_default=sa.text("''")),
        sa.Column("dismissed_at", sa.Text()),
        sa.Column("position", sa.Text(), server_default=sa.text("''")),
        sa.Column("department", sa.Text(), server_default=sa.text("''")),
        sa.Column("phone", sa.Text(), server_default=sa.text("''")),
        sa.Column("email", sa.Text(), server_default=sa.text("''")),
        sa.Column("created_by", sa.Text(), server_default=sa.text("''")),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("login", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column(
            "role",
            sa.Text(),
            server_default=sa.text("'operator'"),
            nullable=False,
        ),
        sa.Column("active", sa.Integer(), server_default=sa.text("1")),
        sa.Column("created_at", sa.Text(), server_default=_now_text),
        sa.Column("last_login", sa.Text(), server_default=sa.text("''")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("login", name="uq_users_login"),
    )

    op.create_table(
        "panels",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("entrance", sa.Text(), server_default=sa.text("''")),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("mac", sa.Text(), nullable=False),
        sa.Column("tags", sa.Text(), server_default=sa.text("''")),
        sa.Column("enabled", sa.Integer(), server_default=sa.text("1")),
        sa.Column("created_at", sa.Text(), server_default=_now_text),
        sa.Column("ip", sa.Text(), server_default=sa.text("''")),
        sa.Column(
            "api_status",
            sa.Text(),
            server_default=sa.text("'unknown'"),
        ),
        sa.Column("last_checked_at", sa.Text(), server_default=sa.text("''")),
        sa.Column("last_online_at", sa.Text(), server_default=sa.text("''")),
        sa.Column("response_time_ms", sa.Integer()),
        sa.Column("device_model", sa.Text(), server_default=sa.text("''")),
        sa.Column("firmware_version", sa.Text(), server_default=sa.text("''")),
        sa.Column("temperature", sa.Float()),
        sa.Column("uptime_seconds", sa.Integer()),
        sa.Column("sip_registered", sa.Integer()),
        sa.Column("reported_mac", sa.Text(), server_default=sa.text("''")),
        sa.Column("last_error", sa.Text(), server_default=sa.text("''")),
        sa.Column("supply_voltage", sa.Float()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mac", name="uq_panels_mac"),
    )
    op.create_index(
        "idx_panels_api_status",
        "panels",
        ["enabled", "api_status"],
    )
    op.create_index(
        "idx_panels_address_entrance",
        "panels",
        ["address", "entrance"],
    )

    op.create_table(
        "uk_groups",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), server_default=sa.text("''")),
        sa.Column("crm_login", sa.Text(), server_default=sa.text("''")),
        sa.Column("crm_password", sa.Text(), server_default=sa.text("''")),
        sa.Column("legal_name", sa.Text(), server_default=sa.text("''")),
        sa.Column("contact_name", sa.Text(), server_default=sa.text("''")),
        sa.Column("phone", sa.Text(), server_default=sa.text("''")),
        sa.Column("email", sa.Text(), server_default=sa.text("''")),
        sa.Column("legal_address", sa.Text(), server_default=sa.text("''")),
        sa.Column("contract_number", sa.Text(), server_default=sa.text("''")),
        sa.Column("created_by", sa.Text(), server_default=sa.text("''")),
        sa.Column("updated_at", sa.Text(), server_default=sa.text("''")),
        sa.Column(
            "cooperation_status",
            sa.Text(),
            server_default=sa.text("'potential'"),
            nullable=False,
        ),
        sa.Column("account_manager", sa.Text(), server_default=sa.text("''")),
        sa.Column("next_contact_at", sa.Text(), server_default=sa.text("''")),
        sa.Column("cooperation_note", sa.Text(), server_default=sa.text("''")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_uk_groups_name"),
    )
    op.create_index("idx_uk_groups_name", "uk_groups", ["name"])

    op.create_table(
        "keys",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("key_type_id", sa.Integer(), nullable=False),
        sa.Column("number", sa.Text(), nullable=False),
        sa.Column(
            "hex_value",
            sa.Text(),
            server_default=sa.text("''"),
            nullable=False,
        ),
        sa.Column("key_type", sa.Text(), server_default=sa.text("''")),
        sa.Column(
            "status",
            sa.Text(),
            server_default=sa.text("'free'"),
            nullable=False,
        ),
        sa.Column("note", sa.Text(), server_default=sa.text("''")),
        sa.Column("is_used", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.Text(), server_default=_now_text, nullable=False),
        sa.Column("updated_at", sa.Text(), server_default=_now_text, nullable=False),
        sa.Column("created_by", sa.Text(), server_default=sa.text("''")),
        sa.ForeignKeyConstraint(
            ["key_type_id"],
            ["key_types.id"],
            name="fk_keys_key_type_id_key_types",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_keys_type_number",
        "keys",
        ["key_type_id", sa.text("lower(number)")],
        unique=True,
    )
    op.create_index(
        "idx_keys_hex_lookup",
        "keys",
        [sa.text("lower(hex_value)")],
    )
    op.create_index("idx_keys_status", "keys", ["status", "key_type_id"])

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

    op.create_table(
        "key_assignments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("key_id", sa.Integer(), nullable=False),
        sa.Column("assignment_type", sa.Text(), nullable=False),
        sa.Column("address", sa.Text(), server_default=sa.text("''")),
        sa.Column("apartment", sa.Text(), server_default=sa.text("''")),
        sa.Column("employee_id", sa.Integer()),
        sa.Column("uk_group_id", sa.Integer()),
        sa.Column("assigned_at", sa.Text(), server_default=_now_text, nullable=False),
        sa.Column("assigned_by", sa.Text(), server_default=sa.text("''")),
        sa.Column("released_at", sa.Text()),
        sa.Column("active", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("note", sa.Text(), server_default=sa.text("''")),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["employees.id"],
            name="fk_key_assignments_employee_id_employees",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["key_id"],
            ["keys.id"],
            name="fk_key_assignments_key_id_keys",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["uk_group_id"],
            ["uk_groups.id"],
            name="fk_key_assignments_uk_group_id_uk_groups",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_key_assignments_one_active",
        "key_assignments",
        ["key_id"],
        unique=True,
        postgresql_where=sa.text("active = 1"),
    )
    op.create_index(
        "idx_key_assignments_lookup",
        "key_assignments",
        ["assignment_type", "active", "assigned_at"],
    )
    op.create_index(
        "idx_key_assignments_key_history",
        "key_assignments",
        ["key_id", "active", "assigned_at"],
    )

    op.create_table(
        "employee_keys",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("key_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column("issued_at", sa.Text(), server_default=_now_text, nullable=False),
        sa.Column("closed_at", sa.Text()),
        sa.Column("close_reason", sa.Text(), server_default=sa.text("''")),
        sa.Column("comment", sa.Text(), server_default=sa.text("''")),
        sa.Column("created_at", sa.Text(), server_default=_now_text, nullable=False),
        sa.Column("updated_at", sa.Text(), server_default=_now_text, nullable=False),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["employees.id"],
            name="fk_employee_keys_employee_id_employees",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["key_id"],
            ["keys.id"],
            name="fk_employee_keys_key_id_keys",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "employee_id",
            "key_id",
            name="uq_employee_keys_employee_key",
        ),
    )
    op.create_index(
        "idx_employee_keys_one_active_employee_per_key",
        "employee_keys",
        ["key_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "idx_employee_keys_employee_history",
        "employee_keys",
        ["employee_id", "status", "issued_at"],
    )

    op.create_table(
        "operation_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("printed_number", sa.Text(), server_default=sa.text("''")),
        sa.Column("hex_value", sa.Text(), nullable=False),
        sa.Column("flat_num", sa.Text(), server_default=sa.text("''")),
        sa.Column("mac", sa.Text(), nullable=False),
        sa.Column("panel_name", sa.Text(), server_default=sa.text("''")),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("response", sa.Text(), server_default=sa.text("''")),
        sa.Column("created_at", sa.Text(), server_default=_now_text),
        sa.Column("address", sa.Text(), server_default=sa.text("''")),
        sa.Column("apartment", sa.Text(), server_default=sa.text("''")),
        sa.Column("username", sa.Text(), server_default=sa.text("''")),
        sa.Column("user_full_name", sa.Text(), server_default=sa.text("''")),
        sa.Column("user_role", sa.Text(), server_default=sa.text("''")),
        sa.Column("action", sa.Text(), server_default=sa.text("''")),
        sa.Column("object_type", sa.Text(), server_default=sa.text("''")),
        sa.Column("object_name", sa.Text(), server_default=sa.text("''")),
        sa.Column("details", sa.Text(), server_default=sa.text("''")),
        sa.Column("ip_address", sa.Text(), server_default=sa.text("''")),
        sa.Column("key_id", sa.Integer()),
        sa.Column("key_type", sa.Text(), server_default=sa.text("''")),
        sa.Column("employee_id", sa.Integer()),
        sa.Column("uk_group_id", sa.Integer()),
        sa.Column("comment", sa.Text(), server_default=sa.text("''")),
        sa.Column("panel_id", sa.Integer()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_operation_log_key_id",
        "operation_log",
        ["key_id"],
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
        sa.Column("created_at", sa.Text(), server_default=_now_text, nullable=False),
        sa.Column("updated_at", sa.Text(), server_default=_now_text, nullable=False),
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
        sa.Column("enabled", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("note", sa.Text(), server_default=sa.text("''")),
        sa.Column("last_sync_at", sa.Text(), server_default=sa.text("''")),
        sa.Column("last_error", sa.Text(), server_default=sa.text("''")),
        sa.Column("created_at", sa.Text(), server_default=_now_text, nullable=False),
        sa.Column("updated_at", sa.Text(), server_default=_now_text, nullable=False),
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


def downgrade() -> None:
    op.drop_table("uk_integrations")
    op.drop_table("uk_notification_drafts")
    op.drop_table("operation_log")
    op.drop_table("employee_keys")
    op.drop_table("key_assignments")
    op.drop_table("uk_group_keys")
    op.drop_table("uk_group_panels")
    op.drop_table("keys")
    op.drop_table("uk_groups")
    op.drop_table("panels")
    op.drop_table("users")
    op.drop_table("employees")
    op.drop_table("key_types")
    op.execute("DROP FUNCTION smart_norm(TEXT)")
