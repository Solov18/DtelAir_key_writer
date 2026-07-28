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
        assert revision == "20260727_04"
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
                    == "20260727_04"
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
