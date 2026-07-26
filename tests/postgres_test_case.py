"""PostgreSQL isolation for the application's database tests.

The test suite never falls back to ``DATABASE_URL``.  A separate database
must be supplied explicitly through ``TEST_DATABASE_URL`` and its name must
clearly identify it as a test database.  Every test receives a fresh schema
inside that database, which is dropped afterwards.
"""

from __future__ import annotations

import re
import unittest
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url

import app.db as database
from app.models import metadata
from app.settings import settings
from tests.conftest import REQUIRED_TEST_DATABASE


_SCHEMA_RE = re.compile(r"^pytest_[a-z0-9_]+$")


def _connection_identity(url: URL) -> tuple[str | None, int | None, str | None]:
    return (url.host, url.port, url.database)


def get_test_database_url() -> str:
    """Return a verified URL for the dedicated PostgreSQL test database."""

    value = settings.database_url
    test_url = make_url(value)
    database_name = test_url.database or ""
    if test_url.drivername != "postgresql+psycopg":
        raise RuntimeError(
            "Test database must use postgresql+psycopg, got "
            f"{test_url.drivername!r}."
        )
    if database_name != REQUIRED_TEST_DATABASE:
        raise RuntimeError(
            f"Test database must be {REQUIRED_TEST_DATABASE!r}, got "
            f"{database_name!r}."
        )
    return value


def _assert_runtime_context(engine, expected_schema: str | None = None) -> tuple[str, str]:
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT current_database(), current_schema()")
        ).one()
    database_name, schema_name = str(row[0]), str(row[1])
    if database_name != REQUIRED_TEST_DATABASE:
        raise RuntimeError(
            "TEST SAFETY ABORT: current_database() returned "
            f"{database_name!r}, expected {REQUIRED_TEST_DATABASE!r}."
        )
    if expected_schema is not None and schema_name != expected_schema:
        raise RuntimeError(
            "TEST SAFETY ABORT: current_schema() returned "
            f"{schema_name!r}, expected {expected_schema!r}."
        )
    return database_name, schema_name


def _schema_url(database_url: str, schema: str) -> str:
    url = make_url(database_url)
    scoped = url.update_query_dict(
        {"options": f"-csearch_path={schema},public"}
    )
    return scoped.render_as_string(hide_password=False)


def _create_smart_norm(engine, schema: str) -> None:
    if not _SCHEMA_RE.fullmatch(schema):  # pragma: no cover - defensive guard
        raise ValueError("Unsafe PostgreSQL test schema name")
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(
            text(
                f'''CREATE FUNCTION "{schema}".smart_norm(value TEXT)
                RETURNS TEXT
                LANGUAGE SQL
                IMMUTABLE
                PARALLEL SAFE
                AS $$
                    SELECT BTRIM(
                        REGEXP_REPLACE(
                            TRANSLATE(LOWER(COALESCE(value, '')), 'ё', 'е'),
                            '[^0-9a-zа-я]+',
                            '',
                            'g'
                        )
                    )
                $$'''
            )
        )


class PostgreSQLTestCase(unittest.TestCase):
    """``unittest`` base class using one disposable PostgreSQL schema/test."""

    _test_database_url: str
    _admin_engine = None

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls._test_database_url = get_test_database_url()
        configured_url = database.get_configured_database_url()
        if configured_url:
            configured_name = make_url(configured_url).database
            if configured_name != REQUIRED_TEST_DATABASE:
                raise RuntimeError(
                    "TEST SAFETY ABORT: app.db engine already points to "
                    f"{configured_name!r}."
                )
        cls._admin_engine = create_engine(
            cls._test_database_url,
            pool_pre_ping=True,
            future=True,
        )
        _assert_runtime_context(cls._admin_engine)

    @classmethod
    def tearDownClass(cls) -> None:
        if cls._admin_engine is not None:
            cls._admin_engine.dispose()
        super().tearDownClass()

    def setUp(self) -> None:
        super().setUp()
        self._schema = f"pytest_{uuid4().hex}"
        try:
            _create_smart_norm(self._admin_engine, self._schema)
            self.database_url = _schema_url(self._test_database_url, self._schema)
            test_engine = database.switch_database(self.database_url)
            database_name, schema_name = _assert_runtime_context(
                test_engine,
                self._schema,
            )
            print(
                "TEST_DATABASE_CONTEXT "
                f"database={database_name} schema={schema_name}"
            )
            metadata.create_all(test_engine)
            database.init_db()
        except BaseException:
            # unittest does not call tearDown() when setUp() fails.  Clean up
            # here as well so even schema-creation/migration failures cannot
            # leave disposable schemas behind.
            database.switch_database(self._test_database_url)
            with self._admin_engine.begin() as connection:
                _assert_runtime_context(self._admin_engine)
                connection.execute(
                    text(f'DROP SCHEMA IF EXISTS "{self._schema}" CASCADE')
                )
            raise

    def tearDown(self) -> None:
        try:
            # Switching away disposes the schema-scoped application engine
            # before the schema is removed.
            database.switch_database(self._test_database_url)
            with self._admin_engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{self._schema}" CASCADE'))
        finally:
            super().tearDown()
