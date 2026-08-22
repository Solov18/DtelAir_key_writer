from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.settings import settings
from tests.conftest import REQUIRED_TEST_DATABASE
from tests.postgres_test_case import (
    _assert_runtime_context,
    _schema_url,
    get_test_database_url,
)


def test_uk_registry_migration_rebuilds_empty_legacy_tables():
    test_url = get_test_database_url()
    admin_engine = create_engine(test_url, pool_pre_ping=True, future=True)
    _assert_runtime_context(admin_engine)
    schema = f"pytest_{uuid4().hex}"
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))

    schema_url = _schema_url(test_url, schema)
    previous_url = settings.database_url
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    try:
        settings.database_url = schema_url
        command.upgrade(config, "20260726_02")
        scoped_engine = create_engine(schema_url, future=True)
        database_name, schema_name = _assert_runtime_context(
            scoped_engine,
            schema,
        )
        print(
            "MIGRATION_TEST_DATABASE_CONTEXT "
            f"database={database_name} schema={schema_name}"
        )
        with scoped_engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO uk_groups(
                        name, crm_login, crm_password, updated_at
                    )
                    VALUES (
                        'УК миграция',
                        'migration-login',
                        'migration-password',
                        ''
                    )
                    """
                )
            )
            for table_name in (
                "uk_group_panels",
                "uk_group_keys",
                "uk_notification_drafts",
                "uk_integrations",
            ):
                count = connection.scalar(
                    text(f'SELECT COUNT(*) FROM "{table_name}"')
                )
                assert count == 0
        scoped_engine.dispose()

        command.upgrade(config, "head")
        scoped_engine = create_engine(schema_url, future=True)
        _assert_runtime_context(scoped_engine, schema)
        inspector = inspect(scoped_engine)
        tables = set(inspector.get_table_names(schema=schema))
        assert {
            "uk_panel_links",
            "uk_key_issues",
            "uk_key_programmings",
            "uk_crm_operations",
            "system_settings",
            "key_panel_states",
            "key_lifecycle_operations",
            "key_lifecycle_steps",
            "key_accesses",
        } <= tables
        assert not {
            "uk_group_panels",
            "uk_group_keys",
            "uk_notification_drafts",
            "uk_integrations",
        } & tables
        columns = {
            column["name"]
            for column in inspector.get_columns("uk_groups", schema=schema)
        }
        assert {"actual_address", "created_at", "archived_at"} <= columns
        assert not {
            "contract_number",
            "cooperation_status",
            "account_manager",
            "next_contact_at",
            "cooperation_note",
        } & columns
        with scoped_engine.connect() as connection:
            revision = connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )
            group = connection.execute(
                text(
                    """
                    SELECT name, crm_login, crm_password, archived_at
                    FROM uk_groups
                    WHERE name = 'УК миграция'
                    """
                )
            ).mappings().one()
        assert revision == "20260822_12"
        assert group["crm_login"] == "migration-login"
        assert group["crm_password"] == "migration-password"
        assert group["archived_at"] is None
        scoped_engine.dispose()

        command.downgrade(config, "20260726_02")
        command.upgrade(config, "head")
        scoped_engine = create_engine(schema_url, future=True)
        _assert_runtime_context(scoped_engine, schema)
        with scoped_engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                    == "20260822_12"
            )
        scoped_engine.dispose()
    finally:
        settings.database_url = previous_url
        with admin_engine.begin() as connection:
            _assert_runtime_context(admin_engine)
            connection.execute(
                text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            )
        admin_engine.dispose()


def test_migration_test_database_name_is_hard_guarded():
    assert REQUIRED_TEST_DATABASE == "key_writer_test"


def test_revision_10_upgrades_to_all_durable_lifecycle_tables():
    test_url = get_test_database_url()
    admin_engine = create_engine(test_url, pool_pre_ping=True, future=True)
    _assert_runtime_context(admin_engine)
    schema = f"pytest_{uuid4().hex}"
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))

    schema_url = _schema_url(test_url, schema)
    previous_url = settings.database_url
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    try:
        settings.database_url = schema_url
        command.upgrade(config, "20260820_10")
        scoped_engine = create_engine(schema_url, future=True)
        _assert_runtime_context(scoped_engine, schema)
        before_tables = set(inspect(scoped_engine).get_table_names(schema=schema))
        assert "key_panel_states" in before_tables
        assert "key_lifecycle_operations" not in before_tables
        assert "key_lifecycle_steps" not in before_tables
        scoped_engine.dispose()

        command.upgrade(config, "head")
        scoped_engine = create_engine(schema_url, future=True)
        _assert_runtime_context(scoped_engine, schema)
        after_tables = set(inspect(scoped_engine).get_table_names(schema=schema))
        assert {
            "key_panel_states",
            "key_lifecycle_operations",
            "key_lifecycle_steps",
            "key_accesses",
        } <= after_tables
        with scoped_engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20260822_12"
        scoped_engine.dispose()
    finally:
        settings.database_url = previous_url
        with admin_engine.begin() as connection:
            _assert_runtime_context(admin_engine)
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()


def test_key_panel_backfill_does_not_activate_free_key_from_audit_history():
    test_url = get_test_database_url()
    admin_engine = create_engine(test_url, pool_pre_ping=True, future=True)
    _assert_runtime_context(admin_engine)
    schema = f"pytest_{uuid4().hex}"
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))

    schema_url = _schema_url(test_url, schema)
    previous_url = settings.database_url
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    try:
        settings.database_url = schema_url
        command.upgrade(config, "20260814_09")
        scoped_engine = create_engine(schema_url, future=True)
        _assert_runtime_context(scoped_engine, schema)
        with scoped_engine.begin() as connection:
            key_type_id = connection.scalar(text(
                "INSERT INTO key_types(name, color) VALUES ('Backfill', '#159ED9') RETURNING id"
            ))
            key_id = connection.scalar(text(
                """
                INSERT INTO keys(key_type_id, number, hex_value, key_type, status, is_used)
                VALUES (:type_id, '000777', 'AA000777', 'Backfill', 'free', 0)
                RETURNING id
                """
            ), {"type_id": key_type_id})
            occupied_key_id = connection.scalar(text(
                """
                INSERT INTO keys(key_type_id, number, hex_value, key_type, status, is_used)
                VALUES (:type_id, '000778', 'AA000778', 'Backfill', 'issued_resident', 1)
                RETURNING id
                """
            ), {"type_id": key_type_id})
            panel_id = connection.scalar(text(
                """
                INSERT INTO panels(address, entrance, name, mac)
                VALUES ('Backfill 1', 'entrance', 'Backfill panel', '08:13:CD:77:00:01')
                RETURNING id
                """
            ))
            connection.execute(text(
                """
                INSERT INTO operation_log(
                    mode, hex_value, mac, status, action, key_id, panel_id
                ) VALUES (
                    'message', 'AA000777', '08:13:CD:77:00:01',
                    'SUCCESS', 'write_key', :key_id, :panel_id
                )
                """
            ), {"key_id": key_id, "panel_id": panel_id})
            connection.execute(text(
                """
                INSERT INTO operation_log(
                    mode, hex_value, mac, status, action, key_id, panel_id
                ) VALUES (
                    'message', 'AA000778', '08:13:CD:77:00:01',
                    'SUCCESS', 'write_key', :key_id, :panel_id
                )
                """
            ), {"key_id": occupied_key_id, "panel_id": panel_id})
        scoped_engine.dispose()

        command.upgrade(config, "head")
        scoped_engine = create_engine(schema_url, future=True)
        _assert_runtime_context(scoped_engine, schema)
        with scoped_engine.connect() as connection:
            rows = connection.execute(text(
                "SELECT state FROM key_panel_states WHERE key_id = :key_id"
            ), {"key_id": key_id}).all()
            uncertain_rows = connection.execute(text(
                """
                SELECT state, last_error, confirmed_at
                FROM key_panel_states WHERE key_id = :key_id
                """
            ), {"key_id": occupied_key_id}).mappings().all()
            operation_count = connection.scalar(text(
                "SELECT COUNT(*) FROM key_lifecycle_operations"
            ))
            free_access_count = connection.scalar(text(
                "SELECT COUNT(*) FROM key_accesses WHERE key_id = :key_id"
            ), {"key_id": key_id})
            occupied_access_count = connection.scalar(text(
                "SELECT COUNT(*) FROM key_accesses WHERE key_id = :key_id"
            ), {"key_id": occupied_key_id})
        assert rows == []
        assert len(uncertain_rows) == 1
        assert uncertain_rows[0]["state"] == "unknown"
        assert "Требуется сверка" in uncertain_rows[0]["last_error"]
        assert uncertain_rows[0]["confirmed_at"] is None
        assert operation_count == 0
        assert free_access_count == 0
        assert occupied_access_count == 0
        scoped_engine.dispose()
    finally:
        settings.database_url = previous_url
        with admin_engine.begin() as connection:
            _assert_runtime_context(admin_engine)
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()
