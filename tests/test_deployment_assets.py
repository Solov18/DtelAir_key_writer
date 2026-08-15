from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_systemd_service_is_non_root_localhost_and_three_workers():
    service = _read("deploy/systemd/key-writer.service")
    assert "User=key-writer" in service
    assert "Group=key-writer" in service
    assert "--host 127.0.0.1" in service
    assert "--port 8100" in service
    assert "--workers 3" in service
    assert "NoNewPrivileges=true" in service


def test_nginx_proxies_only_to_local_application():
    config = _read("deploy/nginx/crm3.dtel.ru.conf")
    assert "server_name crm3.dtel.ru" in config
    assert "proxy_pass http://127.0.0.1:8100" in config
    assert "client_max_body_size" in config
    assert "X-Forwarded-Proto" in config


def test_backup_uses_pg_service_and_verifies_custom_dump():
    script = _read("deploy/scripts/backup-postgres.sh")
    assert "PGSERVICEFILE" in script
    assert "PGPASSFILE" in script
    assert "pg_dump" in script
    assert "--format=custom" in script
    assert "pg_restore --list" in script
    assert "DATABASE_URL" not in script


def test_production_dependencies_do_not_include_test_or_reload_packages():
    requirements = _read("requirements-prod.txt").lower()
    assert "pytest" not in requirements
    assert "watchfiles" not in requirements
    assert "httpx" not in requirements


def test_production_environment_template_uses_safe_defaults():
    environment = _read("deploy/env.production.example")
    assert "APP_ENVIRONMENT=production" in environment
    assert "SESSION_HTTPS_ONLY=true" in environment
    assert "TRUSTED_HOSTS=crm3.dtel.ru,localhost,127.0.0.1" in environment
    assert "DRY_RUN=true" in environment
