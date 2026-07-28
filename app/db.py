"""SQLAlchemy 2 database access.

Application repositories historically use small SQL strings. ``db()`` keeps
their compact API while every statement runs through a SQLAlchemy ``Session``.
Working SQL must be PostgreSQL-native; this module only converts positional
``?`` parameters to SQLAlchemy named parameters.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from threading import RLock
from typing import Any

from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.engine import Result, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.models import TABLES_WITH_ID, metadata
from app.settings import settings


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None
_configured_url = ""
_lock = RLock()


class DatabaseNotMigratedError(RuntimeError):
    """Raised when PostgreSQL is reachable but Alembic was not applied."""


class CompatRow:
    """Mapping row that also supports the legacy integer index access."""

    def __init__(self, values: Sequence[Any], keys: Sequence[str]):
        self._values = tuple(values)
        self._keys = tuple(keys)
        self._mapping = dict(zip(self._keys, self._values))

    def __getitem__(self, key: str | int) -> Any:
        if isinstance(key, int):
            return self._values[key]
        return self._mapping[key]

    def __iter__(self) -> Iterator[Any]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._keys)

    def keys(self) -> tuple[str, ...]:
        return self._keys

    def items(self) -> tuple[tuple[str, Any], ...]:
        return tuple(zip(self._keys, self._values))

    def values(self) -> tuple[Any, ...]:
        return self._values


class CompatResult:
    """Small result facade used by the existing repositories."""

    def __init__(self, result: Result[Any], *, returns_insert_id: bool = False):
        self._result = result
        self._keys = tuple(result.keys()) if result.returns_rows else ()
        self._returns_insert_id = returns_insert_id
        self._lastrowid_loaded = False
        self._lastrowid: int | None = None

    def _wrap(self, row: Any | None) -> CompatRow | None:
        if row is None:
            return None
        return CompatRow(tuple(row), self._keys)

    def fetchone(self) -> CompatRow | None:
        return self._wrap(self._result.fetchone())

    def fetchall(self) -> list[CompatRow]:
        return [self._wrap(row) for row in self._result.fetchall()]  # type: ignore[misc]

    def __iter__(self) -> Iterator[CompatRow]:
        for row in self._result:
            yield self._wrap(row)  # type: ignore[misc]

    @property
    def rowcount(self) -> int:
        return int(getattr(self._result, "rowcount", -1) or 0)

    @property
    def lastrowid(self) -> int | None:
        if self._lastrowid_loaded:
            return self._lastrowid
        self._lastrowid_loaded = True

        if self._returns_insert_id:
            row = self._result.fetchone()
            self._lastrowid = int(row[0]) if row is not None else None
            return self._lastrowid

        raw = getattr(self._result, "lastrowid", None)
        self._lastrowid = int(raw) if raw is not None else None
        return self._lastrowid


def _current_database_url() -> str:
    return settings.database_url


def _assert_test_database_safety(database_url: str) -> None:
    """Prevent any application engine from targeting production under pytest."""

    if os.environ.get("TEST_DATABASE_ACTIVE") != "1":
        return
    database_name = make_url(database_url).database
    if database_name != "key_writer_test":
        raise RuntimeError(
            "TEST SAFETY ABORT: refusing to configure app.db for "
            f"{database_name!r}; only 'key_writer_test' is allowed."
        )


def configure_database(database_url: str | None = None) -> Engine:
    """Configure and return the shared SQLAlchemy engine."""

    global _engine, _session_factory, _configured_url
    with _lock:
        # An explicitly selected engine (notably a schema-scoped test engine)
        # remains active until switch_database() is called.  A plain
        # get_engine()/db() must never silently fall back to settings.
        if database_url is None and _engine is not None:
            return _engine

    target_url = database_url or _current_database_url()
    _assert_test_database_safety(target_url)
    if not target_url.startswith("postgresql+psycopg://"):
        raise ValueError(
            "Рабочая база должна использовать DATABASE_URL вида "
            "postgresql+psycopg://..."
        )

    with _lock:
        if _engine is not None and _configured_url == target_url:
            return _engine
        if _engine is not None:
            _engine.dispose()

        connect_args: dict[str, Any] = {}
        if target_url.startswith("postgresql"):
            connect_args["connect_timeout"] = settings.database_connect_timeout

        engine = create_engine(
            target_url,
            pool_pre_ping=True,
            echo=settings.database_echo,
            connect_args=connect_args,
        )

        _engine = engine
        _session_factory = sessionmaker(
            bind=engine,
            class_=Session,
            autoflush=False,
            expire_on_commit=False,
        )
        _configured_url = target_url
        return engine


def get_configured_database_url() -> str:
    """Return the URL currently bound to the shared engine, if any."""

    with _lock:
        return _configured_url


def switch_database(database_url: str) -> Engine:
    """Atomically replace the engine and session factory with a new URL."""

    global _engine, _session_factory, _configured_url
    _assert_test_database_safety(database_url)
    if not database_url.startswith("postgresql+psycopg://"):
        raise ValueError("Database switch requires postgresql+psycopg:// URL")

    with _lock:
        if _engine is not None:
            _engine.dispose()
        _engine = None
        _session_factory = None
        _configured_url = ""
        settings.database_url = database_url
        return configure_database(database_url)


def get_engine() -> Engine:
    return configure_database()


def _convert_qmark_parameters(
    sql: str,
    params: Sequence[Any],
) -> tuple[str, dict[str, Any]]:
    """Convert qmark placeholders while ignoring quoted string literals."""

    values = list(params)
    output: list[str] = []
    bindings: dict[str, Any] = {}
    value_index = 0
    quote: str | None = None
    index = 0

    while index < len(sql):
        char = sql[index]
        if quote:
            output.append(char)
            if char == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    output.append(sql[index + 1])
                    index += 1
                else:
                    quote = None
        elif char in {"'", '"'}:
            quote = char
            output.append(char)
        elif char == "?":
            if value_index >= len(values):
                raise ValueError("SQL parameters are fewer than placeholders")
            name = f"p{value_index}"
            output.append(f":{name}")
            bindings[name] = values[value_index]
            value_index += 1
        else:
            output.append(char)
        index += 1

    if value_index != len(values):
        raise ValueError("SQL parameters are greater than placeholders")
    return "".join(output), bindings


def _insert_table_name(sql: str) -> str | None:
    match = re.match(
        r"^\s*INSERT\s+INTO\s+([A-Za-z_][A-Za-z0-9_]*)",
        sql,
        re.IGNORECASE,
    )
    return match.group(1).lower() if match else None


class DatabaseSession:
    """Repository-facing facade backed by one SQLAlchemy Session."""

    def __init__(self, session: Session):
        self.session = session

    def execute(
        self,
        sql: str,
        params: Sequence[Any] | Mapping[str, Any] | None = None,
    ) -> CompatResult:
        original_sql = sql

        parameters: Mapping[str, Any]
        if params is None:
            parameters = {}
        elif isinstance(params, Mapping):
            parameters = params
        else:
            sql, parameters = _convert_qmark_parameters(sql, params)

        insert_table = _insert_table_name(original_sql)
        returns_insert_id = False
        if (
            insert_table in TABLES_WITH_ID
            and not re.search(r"\bRETURNING\b", sql, re.IGNORECASE)
        ):
            sql = sql.rstrip().rstrip(";") + " RETURNING id"
            returns_insert_id = True

        result = self.session.execute(text(sql), dict(parameters))
        return CompatResult(result, returns_insert_id=returns_insert_id)

    def executemany(
        self,
        sql: str,
        parameters: Sequence[Sequence[Any] | Mapping[str, Any]],
    ) -> CompatResult:
        parameter_sets = list(parameters)
        if not parameter_sets:
            result = self.session.execute(text("SELECT 1 WHERE 0 = 1"))
            return CompatResult(result)
        first = parameter_sets[0]
        if isinstance(first, Mapping):
            bindings = [dict(item) for item in parameter_sets]  # type: ignore[arg-type]
        else:
            converted_sql, _ = _convert_qmark_parameters(sql, first)
            sql = converted_sql
            bindings = []
            for item in parameter_sets:
                if isinstance(item, Mapping):
                    raise TypeError("Mixed executemany parameter styles")
                bindings.append(
                    {f"p{index}": value for index, value in enumerate(item)}
                )

        result = self.session.execute(text(sql), bindings)
        return CompatResult(result)

    def commit(self) -> None:
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()


@contextmanager
def db() -> Iterator[DatabaseSession]:
    configure_database()
    if _session_factory is None:  # pragma: no cover - defensive invariant
        raise RuntimeError("Database session factory is not configured")
    session = _session_factory()
    connection = DatabaseSession(session)
    try:
        yield connection
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Validate the PostgreSQL connection and migrated schema."""

    engine = configure_database()
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))

    existing_tables = set(inspect(engine).get_table_names())
    required_tables = set(metadata.tables)
    missing = sorted(required_tables - existing_tables)
    if missing:
        raise DatabaseNotMigratedError(
            "PostgreSQL доступен, но схема не создана. "
            "Выполните `alembic upgrade head`. "
            f"Отсутствуют таблицы: {', '.join(missing)}"
        )

    from app.repositories.role_repository import ensure_system_roles

    ensure_system_roles()
