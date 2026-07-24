"""SQLAlchemy 2 table metadata for the application database.

The project intentionally uses SQLAlchemy Core tables instead of ORM mapped
classes.  Two legacy linking tables do not have primary keys, and inventing
ORM identities for them would change the factual database structure.
"""

from sqlalchemy import (
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)


metadata = MetaData()

_now_text = text("CAST(CURRENT_TIMESTAMP AS TEXT)")


key_types = Table(
    "key_types",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", Text, nullable=False),
    Column("color", Text, nullable=False, server_default=text("'#2A9DF4'")),
    Column("note", Text, server_default=text("''")),
    Column("enabled", Integer, nullable=False, server_default=text("1")),
    Column("created_at", Text, nullable=False, server_default=_now_text),
    Column("updated_at", Text, nullable=False, server_default=_now_text),
)
Index("uq_key_types_name_ci", func.lower(key_types.c.name), unique=True)


keys = Table(
    "keys",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "key_type_id",
        Integer,
        ForeignKey("key_types.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("number", Text, nullable=False),
    Column("hex_value", Text, nullable=False, server_default=text("''")),
    Column("key_type", Text, server_default=text("''")),
    Column("status", Text, nullable=False, server_default=text("'free'")),
    Column("note", Text, server_default=text("''")),
    Column("is_used", Integer, nullable=False, server_default=text("0")),
    Column("created_at", Text, nullable=False, server_default=_now_text),
    Column("updated_at", Text, nullable=False, server_default=_now_text),
    Column("created_by", Text, server_default=text("''")),
)
Index(
    "idx_keys_type_number",
    keys.c.key_type_id,
    func.lower(keys.c.number),
    unique=True,
)
Index("idx_keys_hex_lookup", func.lower(keys.c.hex_value))
Index("idx_keys_status", keys.c.status, keys.c.key_type_id)


employees = Table(
    "employees",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("full_name", Text, nullable=False),
    Column("note", Text, server_default=text("''")),
    Column("enabled", Integer, server_default=text("1")),
    Column("created_at", Text, server_default=_now_text),
    Column("updated_at", Text, server_default=text("''")),
    Column("dismissed_at", Text),
    Column("position", Text, server_default=text("''")),
    Column("department", Text, server_default=text("''")),
    Column("phone", Text, server_default=text("''")),
    Column("email", Text, server_default=text("''")),
    Column("created_by", Text, server_default=text("''")),
)


users = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("full_name", Text, nullable=False),
    Column("login", Text, nullable=False, unique=True),
    Column("password_hash", Text, nullable=False),
    Column("role", Text, nullable=False, server_default=text("'operator'")),
    Column("active", Integer, server_default=text("1")),
    Column("created_at", Text, server_default=_now_text),
    Column("last_login", Text, server_default=text("''")),
)


panels = Table(
    "panels",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("address", Text, nullable=False),
    Column("entrance", Text, server_default=text("''")),
    Column("name", Text, nullable=False),
    Column("mac", Text, nullable=False, unique=True),
    Column("tags", Text, server_default=text("''")),
    Column("enabled", Integer, server_default=text("1")),
    Column("created_at", Text, server_default=_now_text),
    Column("ip", Text, server_default=text("''")),
    Column("api_status", Text, server_default=text("'unknown'")),
    Column("last_checked_at", Text, server_default=text("''")),
    Column("last_online_at", Text, server_default=text("''")),
    Column("response_time_ms", Integer),
    Column("device_model", Text, server_default=text("''")),
    Column("firmware_version", Text, server_default=text("''")),
    Column("temperature", Float),
    Column("uptime_seconds", Integer),
    Column("sip_registered", Integer),
    Column("reported_mac", Text, server_default=text("''")),
    Column("last_error", Text, server_default=text("''")),
    Column("supply_voltage", Float),
)
Index("idx_panels_api_status", panels.c.enabled, panels.c.api_status)
Index("idx_panels_address_entrance", panels.c.address, panels.c.entrance)


uk_groups = Table(
    "uk_groups",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", Text, nullable=False, unique=True),
    Column("note", Text, server_default=text("''")),
    Column("crm_login", Text, server_default=text("''")),
    Column("crm_password", Text, server_default=text("''")),
    Column("legal_name", Text, server_default=text("''")),
    Column("contact_name", Text, server_default=text("''")),
    Column("phone", Text, server_default=text("''")),
    Column("email", Text, server_default=text("''")),
    Column("legal_address", Text, server_default=text("''")),
    Column("contract_number", Text, server_default=text("''")),
    Column("created_by", Text, server_default=text("''")),
    Column("updated_at", Text, server_default=text("''")),
    Column(
        "cooperation_status",
        Text,
        nullable=False,
        server_default=text("'potential'"),
    ),
    Column("account_manager", Text, server_default=text("''")),
    Column("next_contact_at", Text, server_default=text("''")),
    Column("cooperation_note", Text, server_default=text("''")),
)
Index("idx_uk_groups_name", uk_groups.c.name)


# These two legacy tables deliberately have neither PKs nor FKs.  Their factual
# structure is retained; see docs/database.md for the associated integrity risk.
uk_group_panels = Table(
    "uk_group_panels",
    metadata,
    Column("group_id", Integer, nullable=False),
    Column("panel_id", Integer, nullable=False),
    UniqueConstraint("group_id", "panel_id"),
)

uk_group_keys = Table(
    "uk_group_keys",
    metadata,
    Column("group_id", Integer, nullable=False),
    Column("key_id", Integer, nullable=False),
    UniqueConstraint("group_id", "key_id"),
)


key_assignments = Table(
    "key_assignments",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "key_id",
        Integer,
        ForeignKey("keys.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("assignment_type", Text, nullable=False),
    Column("address", Text, server_default=text("''")),
    Column("apartment", Text, server_default=text("''")),
    Column(
        "employee_id",
        Integer,
        ForeignKey("employees.id", ondelete="SET NULL"),
    ),
    Column(
        "uk_group_id",
        Integer,
        ForeignKey("uk_groups.id", ondelete="SET NULL"),
    ),
    Column("assigned_at", Text, nullable=False, server_default=_now_text),
    Column("assigned_by", Text, server_default=text("''")),
    Column("released_at", Text),
    Column("active", Integer, nullable=False, server_default=text("1")),
    Column("note", Text, server_default=text("''")),
)
Index(
    "idx_key_assignments_one_active",
    key_assignments.c.key_id,
    unique=True,
    postgresql_where=key_assignments.c.active == 1,
    sqlite_where=key_assignments.c.active == 1,
)
Index(
    "idx_key_assignments_lookup",
    key_assignments.c.assignment_type,
    key_assignments.c.active,
    key_assignments.c.assigned_at,
)
Index(
    "idx_key_assignments_key_history",
    key_assignments.c.key_id,
    key_assignments.c.active,
    key_assignments.c.assigned_at,
)


employee_keys = Table(
    "employee_keys",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "employee_id",
        Integer,
        ForeignKey("employees.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "key_id",
        Integer,
        ForeignKey("keys.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("status", Text, nullable=False, server_default=text("'active'")),
    Column("issued_at", Text, nullable=False, server_default=_now_text),
    Column("closed_at", Text),
    Column("close_reason", Text, server_default=text("''")),
    Column("comment", Text, server_default=text("''")),
    Column("created_at", Text, nullable=False, server_default=_now_text),
    Column("updated_at", Text, nullable=False, server_default=_now_text),
    UniqueConstraint("employee_id", "key_id"),
)
Index(
    "idx_employee_keys_one_active_employee_per_key",
    employee_keys.c.key_id,
    unique=True,
    postgresql_where=employee_keys.c.status == "active",
    sqlite_where=employee_keys.c.status == "active",
)
Index(
    "idx_employee_keys_employee_history",
    employee_keys.c.employee_id,
    employee_keys.c.status,
    employee_keys.c.issued_at,
)


operation_log = Table(
    "operation_log",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("mode", Text, nullable=False),
    Column("printed_number", Text, server_default=text("''")),
    Column("hex_value", Text, nullable=False),
    Column("flat_num", Text, server_default=text("''")),
    Column("mac", Text, nullable=False),
    Column("panel_name", Text, server_default=text("''")),
    Column("status", Text, nullable=False),
    Column("response", Text, server_default=text("''")),
    Column("created_at", Text, server_default=_now_text),
    Column("address", Text, server_default=text("''")),
    Column("apartment", Text, server_default=text("''")),
    Column("username", Text, server_default=text("''")),
    Column("user_full_name", Text, server_default=text("''")),
    Column("user_role", Text, server_default=text("''")),
    Column("action", Text, server_default=text("''")),
    Column("object_type", Text, server_default=text("''")),
    Column("object_name", Text, server_default=text("''")),
    Column("details", Text, server_default=text("''")),
    Column("ip_address", Text, server_default=text("''")),
    Column("key_id", Integer),
    Column("key_type", Text, server_default=text("''")),
    Column("employee_id", Integer),
    Column("uk_group_id", Integer),
    Column("comment", Text, server_default=text("''")),
    Column("panel_id", Integer),
)
Index("idx_operation_log_key_id", operation_log.c.key_id)


uk_notification_drafts = Table(
    "uk_notification_drafts",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "group_id",
        Integer,
        ForeignKey("uk_groups.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("title", Text, nullable=False),
    Column("body", Text, nullable=False),
    Column(
        "category",
        Text,
        nullable=False,
        server_default=text("'announcement'"),
    ),
    Column("channel", Text, nullable=False, server_default=text("'dtel'")),
    Column("audience", Text, nullable=False, server_default=text("'all'")),
    Column("audience_details", Text, server_default=text("''")),
    Column("created_by", Text, server_default=text("''")),
    Column("created_at", Text, nullable=False, server_default=_now_text),
    Column("updated_at", Text, nullable=False, server_default=_now_text),
)
Index(
    "idx_uk_notification_drafts_group",
    uk_notification_drafts.c.group_id,
    uk_notification_drafts.c.created_at.desc(),
)


# Present in the factual SQLite schema even though current application code no
# longer exposes it.  It is retained to avoid silently dropping structure.
uk_integrations = Table(
    "uk_integrations",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "group_id",
        Integer,
        ForeignKey("uk_groups.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("service_name", Text, nullable=False),
    Column("integration_type", Text, nullable=False, server_default=text("'api'")),
    Column("base_url", Text, server_default=text("''")),
    Column("login", Text, server_default=text("''")),
    Column("auth_type", Text, nullable=False, server_default=text("'not_selected'")),
    Column("status", Text, nullable=False, server_default=text("'planned'")),
    Column("enabled", Integer, nullable=False, server_default=text("0")),
    Column("note", Text, server_default=text("''")),
    Column("last_sync_at", Text, server_default=text("''")),
    Column("last_error", Text, server_default=text("''")),
    Column("created_at", Text, nullable=False, server_default=_now_text),
    Column("updated_at", Text, nullable=False, server_default=_now_text),
)
Index(
    "uq_uk_integrations_group_service_ci",
    uk_integrations.c.group_id,
    func.lower(uk_integrations.c.service_name),
    unique=True,
)
Index(
    "idx_uk_integrations_group",
    uk_integrations.c.group_id,
    uk_integrations.c.status,
    uk_integrations.c.service_name,
)


TABLES_WITH_ID = frozenset(
    table.name
    for table in metadata.tables.values()
    if "id" in table.c and table.c.id.primary_key
)
