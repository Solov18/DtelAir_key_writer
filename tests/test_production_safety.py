from __future__ import annotations

import pytest

from app.settings import Settings


def _production_settings(**overrides) -> Settings:
    values = {
        "app_environment": "production",
        "trusted_hosts": "crm3.dtel.ru,localhost,127.0.0.1",
        "database_url": "postgresql+psycopg://user:secret@127.0.0.1/key_writer",
        "session_secret": "a" * 64,
        "session_https_only": True,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_production_settings_accept_safe_configuration():
    _production_settings().validate_production()


@pytest.mark.parametrize(
    "overrides",
    [
        {"session_secret": "short"},
        {"session_https_only": False},
        {"trusted_hosts": "*"},
        {
            "database_url": (
                "postgresql+psycopg://user:secret@127.0.0.1/key_writer_test"
            )
        },
        {
            "database_url": (
                "postgresql+psycopg://user:secret@127.0.0.1/test_key_writer"
            )
        },
        {"database_url": "sqlite:///data/app.db"},
    ],
)
def test_production_settings_fail_closed(overrides):
    with pytest.raises(RuntimeError):
        _production_settings(**overrides).validate_production()
