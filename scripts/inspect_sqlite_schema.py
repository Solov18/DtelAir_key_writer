"""Read-only schema audit for the legacy SQLite database."""

import argparse
import json
import sqlite3
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument(
        "--ddl-only",
        action="store_true",
        help="Print counts, CREATE TABLE statements, foreign keys and index DDL.",
    )
    args = parser.parse_args()

    database_path = args.database.resolve()
    connection = sqlite3.connect(
        f"file:{database_path.as_posix()}?mode=ro&immutable=1",
        uri=True,
    )
    connection.row_factory = sqlite3.Row
    try:
        tables = [
            row["name"]
            for row in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                  AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            )
        ]
        result = {"path": str(database_path), "counts": {}, "schema": {}}
        for table_name in tables:
            result["counts"][table_name] = connection.execute(
                f'SELECT COUNT(*) FROM "{table_name}"'
            ).fetchone()[0]
            result["schema"][table_name] = {
                "table_sql": connection.execute(
                    """
                    SELECT sql
                    FROM sqlite_master
                    WHERE type = 'table' AND name = ?
                    """,
                    (table_name,),
                ).fetchone()["sql"],
                "columns": [
                    dict(row)
                    for row in connection.execute(
                        f'PRAGMA table_info("{table_name}")'
                    )
                ],
                "foreign_keys": [
                    dict(row)
                    for row in connection.execute(
                        f'PRAGMA foreign_key_list("{table_name}")'
                    )
                ],
                "indexes": [
                    {
                        **dict(row),
                        "sql": (
                            connection.execute(
                                """
                                SELECT sql
                                FROM sqlite_master
                                WHERE type = 'index' AND name = ?
                                """,
                                (row["name"],),
                            ).fetchone()["sql"]
                            if connection.execute(
                                """
                                SELECT 1
                                FROM sqlite_master
                                WHERE type = 'index' AND name = ?
                                """,
                                (row["name"],),
                            ).fetchone()
                            else None
                        ),
                    }
                    for row in connection.execute(f'PRAGMA index_list("{table_name}")')
                ],
            }
        if args.ddl_only:
            result = {
                "path": result["path"],
                "counts": result["counts"],
                "schema": {
                    name: {
                        "table_sql": table["table_sql"],
                        "foreign_keys": table["foreign_keys"],
                        "indexes": [
                            {
                                "name": index["name"],
                                "unique": index["unique"],
                                "partial": index["partial"],
                                "sql": index["sql"],
                            }
                            for index in table["indexes"]
                        ],
                    }
                    for name, table in result["schema"].items()
                },
            }
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        connection.close()


if __name__ == "__main__":
    main()
