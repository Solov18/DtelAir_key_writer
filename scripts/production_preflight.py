"""Read-only production checks before an Alembic upgrade.

This script never prints DATABASE_URL or any credential. It is intentionally
separate from tests and refuses a database whose name contains ``test``.
"""

from __future__ import annotations

import argparse

from sqlalchemy import inspect, text

from app.db import get_engine
from app.settings import settings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expect-database", default="key_writer")
    args = parser.parse_args()

    settings.validate_production()
    engine = get_engine()
    with engine.connect() as connection:
        database_name, schema_name = connection.execute(
            text("SELECT current_database(), current_schema()")
        ).one()
        database_name = str(database_name)
        schema_name = str(schema_name)
        if database_name != args.expect_database or "test" in database_name.lower():
            raise RuntimeError(
                f"Preflight refused database={database_name!r}; "
                f"expected {args.expect_database!r}."
            )
        if schema_name != "public":
            raise RuntimeError(
                f"Preflight refused schema={schema_name!r}; expected 'public'."
            )

        tables = set(inspect(connection).get_table_names())
        required = {"keys", "users", "employees", "panels", "alembic_version"}
        missing = sorted(required - tables)
        if missing:
            raise RuntimeError(f"Required migrated tables are missing: {', '.join(missing)}")

        duplicate_hex = int(
            connection.execute(
                text(
                    """
                    SELECT COUNT(*) FROM (
                        SELECT UPPER(hex_value)
                        FROM keys
                        WHERE BTRIM(hex_value) <> ''
                        GROUP BY UPPER(hex_value)
                        HAVING COUNT(*) > 1
                    ) conflicts
                    """
                )
            ).scalar_one()
        )
        duplicate_login = int(
            connection.execute(
                text(
                    """
                    SELECT COUNT(*) FROM (
                        SELECT LOWER(login)
                        FROM users
                        GROUP BY LOWER(login)
                        HAVING COUNT(*) > 1
                    ) conflicts
                    """
                )
            ).scalar_one()
        )
        if duplicate_hex or duplicate_login:
            raise RuntimeError(
                "Uniqueness preflight failed: "
                f"duplicate_hex_groups={duplicate_hex}, "
                f"duplicate_login_groups={duplicate_login}."
            )

        counts = {
            table: int(connection.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar_one())
            for table in ("users", "employees", "panels", "keys")
        }

    print(
        "PRODUCTION_PREFLIGHT_OK "
        f"database={database_name} schema={schema_name} "
        + " ".join(f"{name}={value}" for name, value in counts.items())
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
