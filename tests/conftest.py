"""Install the PostgreSQL test URL before application modules are imported."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from dotenv import dotenv_values
from sqlalchemy.engine import make_url


REQUIRED_TEST_DATABASE = "key_writer_test"


def _target(url: str) -> tuple[str | None, int | None, str | None]:
    parsed = make_url(url)
    return parsed.host, parsed.port, parsed.database


test_database_url = os.environ.get("TEST_DATABASE_URL", "").strip()
if not test_database_url:
    raise pytest.UsageError(
        "TEST_DATABASE_URL is required; pytest is not allowed to use DATABASE_URL."
    )

test_url = make_url(test_database_url)
if test_url.drivername != "postgresql+psycopg":
    raise pytest.UsageError("TEST_DATABASE_URL must use postgresql+psycopg.")
if test_url.database != REQUIRED_TEST_DATABASE:
    raise pytest.UsageError(
        f"TEST_DATABASE_URL must point to {REQUIRED_TEST_DATABASE!r}, got "
        f"{test_url.database!r}."
    )

env_file = Path(__file__).resolve().parents[1] / ".env"
file_values = dotenv_values(env_file)
production_database_url = (
    str(file_values.get("DATABASE_URL") or "").strip()
    or os.environ.get("DATABASE_URL", "").strip()
)
if production_database_url and _target(production_database_url) == _target(
    test_database_url
):
    raise pytest.UsageError(
        "TEST_DATABASE_URL resolves to the same database as DATABASE_URL."
    )

loaded_database = sys.modules.get("app.db")
loaded_engine = getattr(loaded_database, "_engine", None)
if loaded_engine is not None:
    loaded_name = make_url(str(loaded_engine.url)).database
    if loaded_name != REQUIRED_TEST_DATABASE:
        raise pytest.UsageError(
            "app.db engine was created before PostgreSQL test isolation and "
            f"points to {loaded_name!r}. Aborting before test collection."
        )

loaded_settings_module = sys.modules.get("app.settings")
loaded_settings = getattr(loaded_settings_module, "settings", None)
if loaded_settings is not None:
    loaded_settings_name = make_url(loaded_settings.database_url).database
    if loaded_settings_name != REQUIRED_TEST_DATABASE:
        raise pytest.UsageError(
            "app.settings was imported before PostgreSQL test isolation and "
            f"points to {loaded_settings_name!r}. Aborting before test collection."
        )

# Pydantic Settings reads process variables before .env.  This assignment is
# deliberately performed at conftest import time, before pytest imports any
# test module and therefore before repositories can import app.db.
os.environ["DATABASE_URL"] = test_database_url
os.environ["TEST_DATABASE_ACTIVE"] = "1"
