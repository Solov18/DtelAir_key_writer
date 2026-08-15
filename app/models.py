"""SQLAlchemy 2 Core metadata for the PostgreSQL application database."""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    MetaData,
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
Index(
    "idx_keys_number_normalized_type",
    func.coalesce(
        func.nullif(func.ltrim(func.btrim(keys.c.number), "0"), ""),
        "0",
    ),
    keys.c.key_type_id,
    postgresql_where=func.btrim(keys.c.number).op("~")("^[0-9]+$"),
)
Index(
    "uq_keys_hex_nonempty_ci",
    func.upper(keys.c.hex_value),
    unique=True,
    postgresql_where=func.btrim(keys.c.hex_value) != "",
)
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


roles = Table(
    "roles",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("code", Text, nullable=False, unique=True),
    Column("name", Text, nullable=False),
    Column("description", Text, nullable=False, server_default=text("''")),
    Column("is_system", Boolean, nullable=False, server_default=text("false")),
    Column("created_at", Text, nullable=False, server_default=_now_text),
    Column("updated_at", Text, nullable=False, server_default=_now_text),
)
Index("uq_roles_name_ci", func.lower(roles.c.name), unique=True)


permissions = Table(
    "permissions",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("code", Text, nullable=False, unique=True),
    Column("name", Text, nullable=False),
    Column("description", Text, nullable=False, server_default=text("''")),
)


role_permissions = Table(
    "role_permissions",
    metadata,
    Column(
        "role_id",
        Integer,
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "permission_id",
        Integer,
        ForeignKey("permissions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


users = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("full_name", Text, nullable=False),
    Column("login", Text, nullable=False, unique=True),
    Column("password_hash", Text, nullable=False),
    Column(
        "role_id",
        Integer,
        ForeignKey("roles.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("active", Integer, server_default=text("1")),
    Column("created_at", Text, server_default=_now_text),
    Column("last_login", Text, server_default=text("''")),
)
Index("uq_users_login_ci", func.lower(users.c.login), unique=True)


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
    Column("last_checked_at", DateTime(timezone=True)),
    Column("last_online_at", DateTime(timezone=True)),
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

panel_monitor_state = Table(
    "panel_monitor_state",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("status", Text, nullable=False, server_default=text("'idle'")),
    Column("total", Integer, nullable=False, server_default=text("0")),
    Column("completed", Integer, nullable=False, server_default=text("0")),
    Column("online", Integer, nullable=False, server_default=text("0")),
    Column("failed", Integer, nullable=False, server_default=text("0")),
    Column("active_panel_ids", JSON, nullable=False, server_default=text("'[]'::json")),
    Column("requested_at", DateTime(timezone=True)),
    Column("started_at", DateTime(timezone=True)),
    Column("finished_at", DateTime(timezone=True)),
    Column("heartbeat_at", DateTime(timezone=True)),
    Column("requested_by", Text, nullable=False, server_default=text("''")),
    Column("last_error", Text, nullable=False, server_default=text("''")),
)


system_settings = Table(
    "system_settings",
    metadata,
    Column("key", Text, primary_key=True),
    Column("value", Text, nullable=False),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    Column("updated_by", Text, nullable=False, server_default=text("''")),
)


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
    Column("actual_address", Text, server_default=text("''")),
    Column("created_by", Text, server_default=text("''")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("archived_at", DateTime(timezone=True)),
)
Index("idx_uk_groups_name", uk_groups.c.name)


uk_panel_links = Table(
    "uk_panel_links",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "uk_group_id",
        Integer,
        ForeignKey("uk_groups.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "panel_id",
        Integer,
        ForeignKey("panels.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("apartment", Text, nullable=False),
    Column("comment", Text, server_default=text("''")),
    Column("active", Boolean, nullable=False, server_default=text("true")),
    Column("created_by", Text, server_default=text("''")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("detached_at", DateTime(timezone=True)),
)
Index(
    "uq_uk_panel_links_group_panel_active",
    uk_panel_links.c.uk_group_id,
    uk_panel_links.c.panel_id,
    unique=True,
    postgresql_where=uk_panel_links.c.active.is_(True),
)
Index(
    "uq_uk_panel_links_panel_active",
    uk_panel_links.c.panel_id,
    unique=True,
    postgresql_where=uk_panel_links.c.active.is_(True),
)
Index("idx_uk_panel_links_group", uk_panel_links.c.uk_group_id, uk_panel_links.c.active)


uk_key_issues = Table(
    "uk_key_issues",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "uk_group_id",
        Integer,
        ForeignKey("uk_groups.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "key_id",
        Integer,
        ForeignKey("keys.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("status", Text, nullable=False, server_default=text("'pending'")),
    Column("comment", Text, server_default=text("''")),
    Column("issued_by", Text, server_default=text("''")),
    Column("issued_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("released_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "status IN ('pending', 'active', 'released', 'archived')",
        name="ck_uk_key_issues_status",
    ),
)
Index(
    "uq_uk_key_issues_key_active",
    uk_key_issues.c.key_id,
    unique=True,
    postgresql_where=uk_key_issues.c.status.in_(("pending", "active")),
)
Index("idx_uk_key_issues_group", uk_key_issues.c.uk_group_id, uk_key_issues.c.status)


uk_key_programmings = Table(
    "uk_key_programmings",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "issue_id",
        Integer,
        ForeignKey("uk_key_issues.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "panel_link_id",
        Integer,
        ForeignKey("uk_panel_links.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("apartment", Text, nullable=False),
    Column("is_primary", Boolean, nullable=False, server_default=text("false")),
    Column("active", Boolean, nullable=False, server_default=text("true")),
    Column("status", Text, nullable=False, server_default=text("'pending'")),
    Column("last_error", Text, server_default=text("''")),
    Column("programmed_at", DateTime(timezone=True)),
    Column("removed_at", DateTime(timezone=True)),
    Column("unlinked_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "status IN ('pending', 'success', 'error', 'dry_run', 'unlinked', 'removed')",
        name="ck_uk_key_programmings_status",
    ),
)
Index(
    "uq_uk_key_programmings_issue_panel_active",
    uk_key_programmings.c.issue_id,
    uk_key_programmings.c.panel_link_id,
    unique=True,
    postgresql_where=uk_key_programmings.c.active.is_(True),
)
Index(
    "uq_uk_key_programmings_primary_active",
    uk_key_programmings.c.issue_id,
    unique=True,
    postgresql_where=(
        uk_key_programmings.c.active.is_(True)
        & uk_key_programmings.c.is_primary.is_(True)
    ),
)
Index("idx_uk_key_programmings_issue", uk_key_programmings.c.issue_id, uk_key_programmings.c.active)


uk_crm_operations = Table(
    "uk_crm_operations",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "programming_id",
        Integer,
        ForeignKey("uk_key_programmings.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("operation", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("idempotency_key", Text, nullable=False, unique=True),
    Column("attempt_number", Integer, nullable=False, server_default=text("1")),
    Column("safe_response", Text, server_default=text("''")),
    Column("requested_by", Text, server_default=text("''")),
    Column("started_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("completed_at", DateTime(timezone=True)),
    CheckConstraint(
        "operation IN ('add', 'remove')",
        name="ck_uk_crm_operations_operation",
    ),
    CheckConstraint(
        "status IN ('pending', 'success', 'error', 'dry_run')",
        name="ck_uk_crm_operations_status",
    ),
)
Index(
    "idx_uk_crm_operations_programming",
    uk_crm_operations.c.programming_id,
    uk_crm_operations.c.started_at.desc(),
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


TABLES_WITH_ID = frozenset(
    table.name
    for table in metadata.tables.values()
    if "id" in table.c and table.c.id.primary_key
)
