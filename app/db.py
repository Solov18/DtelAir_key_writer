"""SQLAlchemy 2 database access.

Application repositories historically use small SQL strings.  ``db()`` keeps
their compact API while every statement now runs through a SQLAlchemy
``Session``.  The adapter is intentionally temporary-friendly: it accepts the
old positional ``?`` parameters and rewrites the small SQLite-only SQL surface
for PostgreSQL without changing repository business rules.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Any

from sqlalchemy import Engine, create_engine, event, inspect, text
from sqlalchemy.engine import Result
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.models import TABLES_WITH_ID, metadata
from app.search_utils import normalize_search_text
from app.settings import settings


# Compatibility for the existing isolated unit tests.  Production never reads
# APP_DB_PATH and always uses DATABASE_URL from settings/.env.
DB_PATH: Path | None = None

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None
_configured_url = ""
_lock = RLock()


class DatabaseNotMigratedError(RuntimeError):
    """Raised when PostgreSQL is reachable but Alembic was not applied."""


class CompatRow(Mapping[str, Any]):
    """Mapping row that also supports the legacy integer index access."""

    def __init__(self, values: Sequence[Any], keys: Sequence[str]):
        self._values = tuple(values)
        self._keys = tuple(keys)
        self._mapping = dict(zip(self._keys, self._values))

    def __getitem__(self, key: str | int) -> Any:
        if isinstance(key, int):
            return self._values[key]
        return self._mapping[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._keys)

    def __len__(self) -> int:
        return len(self._keys)


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
    if DB_PATH is not None:
        return f"sqlite+pysqlite:///{Path(DB_PATH).resolve().as_posix()}"
    return settings.database_url


def configure_database(database_url: str | None = None) -> Engine:
    """Configure and return the shared SQLAlchemy engine."""

    global _engine, _session_factory, _configured_url
    target_url = database_url or _current_database_url()

    with _lock:
        if _engine is not None and _configured_url == target_url:
            return _engine
        if _engine is not None:
            _engine.dispose()

        connect_args: dict[str, Any] = {}
        if target_url.startswith("postgresql"):
            connect_args["connect_timeout"] = settings.database_connect_timeout

        engine_options: dict[str, Any] = {
            "pool_pre_ping": True,
            "echo": settings.database_echo,
            "connect_args": connect_args,
        }
        if target_url.startswith("sqlite"):
            engine_options["poolclass"] = NullPool

        engine = create_engine(
            target_url,
            **engine_options,
        )
        if engine.dialect.name == "sqlite":
            _configure_sqlite_test_engine(engine)

        _engine = engine
        _session_factory = sessionmaker(
            bind=engine,
            class_=Session,
            autoflush=False,
            expire_on_commit=False,
        )
        _configured_url = target_url
        return engine


def get_engine() -> Engine:
    return configure_database()


def _configure_sqlite_test_engine(engine: Engine) -> None:
    """SQLite support is restricted to tests and the one-way import source."""

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection: Any, _connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()
        dbapi_connection.create_function(
            "SMART_NORM",
            1,
            normalize_search_text,
            deterministic=True,
        )


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


def _strip_function(sql: str, function_name: str) -> str:
    """Remove a one-argument wrapper while preserving nested expressions."""

    needle = function_name.lower() + "("
    result = sql
    search_from = 0
    while True:
        start = result.lower().find(needle, search_from)
        if start < 0:
            return result
        open_paren = start + len(function_name)
        depth = 0
        quote: str | None = None
        close_paren = -1
        for index in range(open_paren, len(result)):
            char = result[index]
            if quote:
                if char == quote:
                    quote = None
                continue
            if char in {"'", '"'}:
                quote = char
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    close_paren = index
                    break
        if close_paren < 0:
            return result
        inner = result[open_paren + 1 : close_paren]
        result = result[:start] + inner + result[close_paren + 1 :]
        search_from = start + len(inner)


def _split_top_level_comma(value: str) -> tuple[str, str | None]:
    depth = 0
    quote: str | None = None
    for index, char in enumerate(value):
        if quote:
            if char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            return value[:index].strip(), value[index + 1 :].strip()
    return value.strip(), None


def _replace_group_concat(sql: str) -> str:
    result = sql
    search_from = 0
    needle = "group_concat("
    while True:
        start = result.lower().find(needle, search_from)
        if start < 0:
            return result
        open_paren = start + len("group_concat")
        depth = 0
        quote: str | None = None
        close_paren = -1
        for index in range(open_paren, len(result)):
            char = result[index]
            if quote:
                if char == quote:
                    quote = None
                continue
            if char in {"'", '"'}:
                quote = char
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    close_paren = index
                    break
        if close_paren < 0:
            return result

        expression, separator = _split_top_level_comma(
            result[open_paren + 1 : close_paren]
        )
        separator = separator or "','"
        if expression.upper().startswith("DISTINCT "):
            expression = expression[9:].strip()
            replacement = (
                f"STRING_AGG(DISTINCT CAST({expression} AS TEXT), {separator})"
            )
        else:
            replacement = f"STRING_AGG(CAST({expression} AS TEXT), {separator})"
        result = result[:start] + replacement + result[close_paren + 1 :]
        search_from = start + len(replacement)


def _rewrite_postgresql_sql(sql: str) -> str:
    rewritten = _replace_group_concat(sql)
    rewritten = _strip_function(rewritten, "datetime")
    rewritten = re.sub(
        r"\bCURRENT_TIMESTAMP\b",
        "CAST(CURRENT_TIMESTAMP AS TEXT)",
        rewritten,
        flags=re.IGNORECASE,
    )
    rewritten = re.sub(
        r"([\w.]+)\s*=\s*\?\s+COLLATE\s+NOCASE",
        r"LOWER(\1) = LOWER(?)",
        rewritten,
        flags=re.IGNORECASE,
    )
    rewritten = re.sub(
        r"([\w.]+)\s+COLLATE\s+NOCASE",
        r"LOWER(\1)",
        rewritten,
        flags=re.IGNORECASE,
    )
    rewritten = re.sub(
        r"([\w.]+)\s+NOT\s+GLOB\s+'\*\[\^0-9\]\*'",
        r"\1 !~ '[^0-9]'",
        rewritten,
        flags=re.IGNORECASE,
    )
    is_insert_ignore = bool(
        re.search(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", rewritten, re.IGNORECASE)
    )
    rewritten = re.sub(
        r"\bINSERT\s+OR\s+IGNORE\s+INTO\b",
        "INSERT INTO",
        rewritten,
        flags=re.IGNORECASE,
    )
    if is_insert_ignore:
        rewritten = rewritten.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    return rewritten


def _insert_table_name(sql: str) -> str | None:
    match = re.match(
        r"^\s*INSERT\s+(?:OR\s+IGNORE\s+)?INTO\s+([A-Za-z_][A-Za-z0-9_]*)",
        sql,
        re.IGNORECASE,
    )
    return match.group(1).lower() if match else None


class DatabaseSession:
    """Repository-facing facade backed by one SQLAlchemy Session."""

    def __init__(self, session: Session):
        self.session = session
        bind = session.get_bind()
        self.dialect_name = bind.dialect.name

    def execute(
        self,
        sql: str,
        params: Sequence[Any] | Mapping[str, Any] | None = None,
    ) -> CompatResult:
        original_sql = sql
        if self.dialect_name == "postgresql":
            sql = _rewrite_postgresql_sql(sql)

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
            self.dialect_name == "postgresql"
            and insert_table in TABLES_WITH_ID
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
        if self.dialect_name == "postgresql":
            sql = _rewrite_postgresql_sql(sql)

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
    """Validate PostgreSQL schema; create metadata only for isolated tests."""

    engine = configure_database()
    if engine.dialect.name == "sqlite":
        metadata.create_all(engine)
        return

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
