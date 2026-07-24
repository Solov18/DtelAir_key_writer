"""One-way, read-only import of employees and users into PostgreSQL.

The legacy SQLite file is opened with ``mode=ro&immutable=1`` and its SHA-256
is checked before and after the operation.  Existing PostgreSQL rows are never
overwritten: matching rows make the script idempotent, conflicting rows abort
the transaction.
"""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, func, inspect, insert, select, text
from sqlalchemy.orm import Session

from app.models import employees, users
from app.settings import settings


MIGRATED_TABLES = (employees, users)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def open_legacy_database(path: Path) -> sqlite3.Connection:
    resolved = path.resolve()
    connection = sqlite3.connect(
        f"file:{resolved.as_posix()}?mode=ro&immutable=1",
        uri=True,
    )
    connection.row_factory = sqlite3.Row
    return connection


def read_source_rows(
    connection: sqlite3.Connection,
    table_name: str,
    columns: list[str],
) -> list[dict[str, Any]]:
    column_sql = ", ".join(f'"{column}"' for column in columns)
    return [
        dict(row)
        for row in connection.execute(
            f'SELECT {column_sql} FROM "{table_name}" ORDER BY id'
        )
    ]


def source_counts(connection: sqlite3.Connection) -> dict[str, int]:
    table_names = [
        row["name"]
        for row in connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        )
    ]
    return {
        table_name: int(
            connection.execute(
                f'SELECT COUNT(*) FROM "{table_name}"'
            ).fetchone()[0]
        )
        for table_name in table_names
    }


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row[key] for key in sorted(row)}


def _reset_postgresql_sequence(session: Session, table_name: str) -> None:
    if session.get_bind().dialect.name != "postgresql":
        return
    if table_name not in {"employees", "users"}:
        raise ValueError(f"Unexpected sequence table: {table_name}")
    session.execute(
        text(
            f"""
            SELECT setval(
                pg_get_serial_sequence('{table_name}', 'id'),
                COALESCE(MAX(id), 1),
                COUNT(*) > 0
            )
            FROM {table_name}
            """
        )
    )


def migrate_rows(
    source: sqlite3.Connection,
    engine: Engine,
    *,
    verify_only: bool = False,
) -> dict[str, tuple[int, int]]:
    missing_tables = {
        table.name for table in MIGRATED_TABLES
    } - set(inspect(engine).get_table_names())
    if missing_tables:
        raise RuntimeError(
            "В PostgreSQL отсутствуют таблицы: "
            f"{', '.join(sorted(missing_tables))}. "
            "Сначала выполните `alembic upgrade head`."
        )

    results: dict[str, tuple[int, int]] = {}
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        with session.begin():
            inserted_tables: list[str] = []
            for table in MIGRATED_TABLES:
                columns = [column.name for column in table.columns]
                source_rows = read_source_rows(source, table.name, columns)
                source_by_id = {
                    int(row["id"]): _normalize_row(row)
                    for row in source_rows
                }
                target_rows = [
                    dict(row)
                    for row in session.execute(
                        select(*table.columns).order_by(table.c.id)
                    ).mappings()
                ]
                target_by_id = {
                    int(row["id"]): _normalize_row(row)
                    for row in target_rows
                }

                extra_ids = sorted(set(target_by_id) - set(source_by_id))
                if extra_ids:
                    raise RuntimeError(
                        f"Таблица {table.name} уже содержит ID, которых нет "
                        f"в SQLite: {extra_ids[:10]}"
                    )

                conflicts = [
                    row_id
                    for row_id in set(source_by_id) & set(target_by_id)
                    if source_by_id[row_id] != target_by_id[row_id]
                ]
                if conflicts:
                    raise RuntimeError(
                        f"Конфликт данных в {table.name}, ID: {sorted(conflicts)[:10]}"
                    )

                missing_rows = [
                    row
                    for row in source_rows
                    if int(row["id"]) not in target_by_id
                ]
                if missing_rows and verify_only:
                    raise RuntimeError(
                        f"{table.name}: в PostgreSQL отсутствует "
                        f"{len(missing_rows)} записей"
                    )
                if missing_rows:
                    session.execute(insert(table), missing_rows)
                    inserted_tables.append(table.name)

                target_count = int(
                    session.scalar(select(func.count()).select_from(table)) or 0
                )
                source_count = len(source_rows)
                results[table.name] = (source_count, target_count)
                if source_count != target_count:
                    raise RuntimeError(
                        f"Количество {table.name} не совпало: "
                        f"SQLite={source_count}, PostgreSQL={target_count}"
                    )

            for table_name in inserted_tables:
                _reset_postgresql_sequence(session, table_name)

    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Перенос employees и users из SQLite в PostgreSQL."
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("data/app.db"),
        help="Исходный SQLite-файл (открывается только для чтения).",
    )
    parser.add_argument(
        "--database-url",
        default=settings.database_url,
        help="Целевой SQLAlchemy URL; по умолчанию DATABASE_URL из .env.",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Только сверить строки и количество, ничего не добавлять.",
    )
    args = parser.parse_args()

    source_path = args.source.resolve()
    before_hash = file_sha256(source_path)
    source = open_legacy_database(source_path)
    try:
        counts = source_counts(source)
        unexpected = {
            name: count
            for name, count in counts.items()
            if name not in {"employees", "users"} and count
        }
        if unexpected:
            print(
                "ПРЕДУПРЕЖДЕНИЕ: в других SQLite-таблицах есть данные, "
                "но по заданию они не переносятся:"
            )
            for name, count in unexpected.items():
                print(f"  {name}: {count}")

        engine = create_engine(args.database_url, pool_pre_ping=True)
        try:
            results = migrate_rows(
                source,
                engine,
                verify_only=args.verify_only,
            )
        finally:
            engine.dispose()
    finally:
        source.close()

    after_hash = file_sha256(source_path)
    if before_hash != after_hash:
        raise RuntimeError(
            "Контрольная сумма исходного SQLite-файла изменилась; "
            "операция остановлена."
        )

    action = "Проверка" if args.verify_only else "Перенос"
    print(f"{action} завершён.")
    for table_name, (sqlite_count, postgres_count) in results.items():
        print(
            f"  {table_name}: SQLite={sqlite_count}, "
            f"PostgreSQL={postgres_count} — совпадает"
        )
    print(f"SQLite SHA-256 не изменился: {after_hash}")


if __name__ == "__main__":
    main()
