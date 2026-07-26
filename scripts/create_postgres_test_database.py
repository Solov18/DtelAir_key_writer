"""Create the dedicated PostgreSQL database used by the test suite.

The command intentionally requires an administrator URL.  Application tests
never create databases and never use ``DATABASE_URL`` as a fallback.
"""

from __future__ import annotations

import argparse
import os
import re

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.settings import settings


_DATABASE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*_test$")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a protected PostgreSQL database for pytest."
    )
    parser.add_argument(
        "--admin-url",
        default=os.environ.get("POSTGRES_ADMIN_URL", ""),
        help="PostgreSQL administrator URL (or POSTGRES_ADMIN_URL).",
    )
    parser.add_argument(
        "--database",
        default=f"{make_url(settings.database_url).database}_test",
        help="Name for the dedicated test database (must end with _test).",
    )
    parser.add_argument(
        "--owner",
        default=make_url(settings.database_url).username or "",
        help="Role that owns the new database.",
    )
    args = parser.parse_args()

    if not args.admin_url:
        raise SystemExit("Provide --admin-url or POSTGRES_ADMIN_URL.")
    if not _DATABASE_RE.fullmatch(args.database):
        raise SystemExit("The test database name must end with _test.")
    if args.database == make_url(settings.database_url).database:
        raise SystemExit("Refusing to use DATABASE_URL's working database.")
    if args.owner and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", args.owner):
        raise SystemExit("Invalid PostgreSQL role name.")

    engine = create_engine(args.admin_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            exists = connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": args.database},
            )
            if not exists:
                owner_sql = f' OWNER "{args.owner}"' if args.owner else ""
                connection.execute(
                    text(f'CREATE DATABASE "{args.database}"{owner_sql}')
                )
                print(f"Created PostgreSQL test database: {args.database}")
            else:
                print(f"PostgreSQL test database already exists: {args.database}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
