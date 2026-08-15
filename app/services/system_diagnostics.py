"""Safe, read-only diagnostics for the administrative connections page."""

from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.db import get_engine
from app.repositories.panel_monitor_repository import get_monitor_state
from app.repositories.system_settings_repository import get_monitor_runtime_settings
from app.settings import settings


APPLICATION_STARTED_AT = datetime.now(timezone.utc)
APPLICATION_STARTED_MONOTONIC = time.monotonic()
PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKUP_DIRECTORY = Path(os.environ.get("BACKUP_DIR", "/var/backups/key-writer"))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _safe_run(command: list[str], timeout: float = 2.0) -> str:
    """Run a fixed command without a shell and return only bounded stdout."""

    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()[:500]


def _alembic_head() -> str:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    return str(ScriptDirectory.from_config(config).get_current_head() or "")


def database_diagnostics() -> dict[str, Any]:
    url = make_url(settings.database_url)
    result: dict[str, Any] = {
        "status": "error",
        "status_label": "Ошибка",
        "message": "PostgreSQL недоступен",
        "checked_at": utc_now(),
        "connected": False,
        "host": url.host or "—",
        "port": url.port or 5432,
        "name": url.database or "—",
        "user": url.username or "—",
        "current_database": "—",
        "server_version": "—",
        "alembic_current": "—",
        "alembic_head": "—",
        "revision_matches": False,
        "ping_ms": None,
        "database_size": None,
        "active_connections": None,
        "application_connections": None,
        "pool_status": "Недоступно",
        "last_success_at": None,
        "technical": {
            "database_echo": bool(settings.database_echo),
            "connect_timeout": int(settings.database_connect_timeout),
            "pool_size": int(settings.database_pool_size),
            "max_overflow": int(settings.database_max_overflow),
            "pool_timeout": int(settings.database_pool_timeout),
            "pool_recycle": int(settings.database_pool_recycle),
        },
    }
    started = time.perf_counter()
    try:
        engine = get_engine()
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT current_database() AS database_name,
                           version() AS server_version,
                           pg_size_pretty(pg_database_size(current_database())) AS database_size,
                           count(*) FILTER (WHERE state = 'active') AS active_connections,
                           count(*) FILTER (
                               WHERE application_name = current_setting('application_name', true)
                                 AND pid <> pg_backend_pid()
                           ) + 1 AS application_connections
                    FROM pg_stat_activity
                    WHERE datname = current_database()
                    GROUP BY current_database(), version()
                    """
                )
            ).mappings().one()
            current_revision = MigrationContext.configure(connection).get_current_revision()
        head_revision = _alembic_head()
        ping_ms = max(0.1, round((time.perf_counter() - started) * 1000, 1))
        current_revision = str(current_revision or "")
        matches = bool(current_revision and current_revision == head_revision)
        result.update(
            {
                "status": "ok" if matches else "warning",
                "status_label": "OK" if matches else "Предупреждение",
                "message": (
                    "Подключение и схема исправны"
                    if matches
                    else "Подключение работает, но Alembic revision отстаёт от head"
                ),
                "connected": True,
                "current_database": str(row["database_name"]),
                "server_version": str(row["server_version"]).split(",", 1)[0],
                "alembic_current": current_revision or "Не определена",
                "alembic_head": head_revision or "Не определена",
                "revision_matches": matches,
                "ping_ms": ping_ms,
                "database_size": str(row["database_size"]),
                "active_connections": int(row["active_connections"] or 0),
                "application_connections": int(row["application_connections"] or 0),
                "pool_status": engine.pool.status(),
                "last_success_at": utc_now(),
            }
        )
    except Exception:
        # Driver errors can include connection details. Never expose them.
        result["ping_ms"] = max(0.1, round((time.perf_counter() - started) * 1000, 1))
    return result


def panel_registry_diagnostics() -> dict[str, Any]:
    result: dict[str, Any] = {
        "total": 0,
        "enabled": 0,
        "online": 0,
        "offline": 0,
        "stale": 0,
        "average_response_ms": None,
        "median_response_ms": None,
        "last_monitor_at": None,
        "last_success_at": None,
    }
    runtime = get_monitor_runtime_settings()
    stale_seconds = int(runtime.panel_monitor_stale_seconds)
    with get_engine().connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT enabled, api_status, last_checked_at, last_online_at,
                       response_time_ms
                FROM panels
                """
            )
        ).mappings().all()
    now = utc_now()
    response_times: list[int] = []
    for row in rows:
        enabled = bool(row["enabled"])
        checked_at = _aware(row["last_checked_at"])
        result["enabled"] += int(enabled)
        result["online"] += int(enabled and row["api_status"] == "online")
        result["offline"] += int(
            enabled and row["api_status"] in {"offline", "auth_error", "error"}
        )
        result["stale"] += int(
            enabled
            and (
                checked_at is None
                or (now - checked_at).total_seconds() > stale_seconds
            )
        )
        if row["response_time_ms"] is not None:
            response_times.append(int(row["response_time_ms"]))
        online_at = _aware(row["last_online_at"])
        if online_at and (
            result["last_success_at"] is None or online_at > result["last_success_at"]
        ):
            result["last_success_at"] = online_at
    result["total"] = len(rows)
    if response_times:
        result["average_response_ms"] = round(sum(response_times) / len(response_times), 1)
        result["median_response_ms"] = round(float(median(response_times)), 1)
    state = get_monitor_state()
    result["last_monitor_at"] = _aware(state.get("finished_at"))
    return result


def monitoring_diagnostics() -> dict[str, Any]:
    runtime = get_monitor_runtime_settings()
    state = get_monitor_state()
    now = utc_now()
    heartbeat = _aware(state.get("heartbeat_at"))
    finished_at = _aware(state.get("finished_at"))
    last_activity = heartbeat or finished_at
    heartbeat_stale = bool(
        runtime.panel_monitor_enabled
        and (
            last_activity is None
            or (now - last_activity).total_seconds()
            > runtime.panel_monitor_stale_seconds
        )
    )
    if not runtime.panel_monitor_enabled:
        status, label, message = "muted", "Не настроено", "Мониторинг выключен"
    elif state.get("status") == "failed":
        status, label, message = "error", "Ошибка", "Последний цикл завершился ошибкой"
    elif heartbeat_stale:
        status, label, message = "warning", "Предупреждение", "Heartbeat мониторинга устарел"
    else:
        status, label, message = "ok", "OK", "Мониторинг работает штатно"
    next_cycle_at = None
    if finished_at and runtime.panel_monitor_enabled:
        next_cycle_at = finished_at.timestamp() + runtime.panel_monitor_interval_seconds
        next_cycle_at = datetime.fromtimestamp(next_cycle_at, tz=timezone.utc)
    return {
        "status": status,
        "status_label": label,
        "message": message,
        "checked_at": now,
        "enabled": runtime.panel_monitor_enabled,
        "leader_active": bool(state.get("status") == "running" and not heartbeat_stale),
        "cycle_status": str(state.get("status") or "idle"),
        "heartbeat": heartbeat,
        "heartbeat_stale": heartbeat_stale,
        "last_cycle_at": finished_at,
        "total": int(state.get("total") or 0),
        "completed": int(state.get("completed") or 0),
        "online": int(state.get("online") or 0),
        "failed": int(state.get("failed") or 0),
        "active_panels": len(state.get("active_panel_ids") or []),
        "next_cycle_at": next_cycle_at,
        "runtime": runtime,
    }


def application_diagnostics() -> dict[str, Any]:
    workers = os.environ.get("WEB_CONCURRENCY") or os.environ.get("UVICORN_WORKERS")
    if not workers and "--workers" in sys.argv:
        index = sys.argv.index("--workers")
        if index + 1 < len(sys.argv):
            workers = sys.argv[index + 1]
    commit = os.environ.get("APP_GIT_COMMIT", "").strip()
    if not commit and shutil.which("git") and (PROJECT_ROOT / ".git").exists():
        commit = _safe_run(["git", "-C", str(PROJECT_ROOT), "rev-parse", "--short", "HEAD"])
    return {
        "status": "ok",
        "status_label": "OK",
        "message": "Приложение отвечает",
        "checked_at": utc_now(),
        "environment": settings.app_environment,
        "dry_run": bool(settings.dry_run),
        "python_version": platform.python_version(),
        "uptime_seconds": max(0, int(time.monotonic() - APPLICATION_STARTED_MONOTONIC)),
        "pid": os.getpid(),
        "workers": int(workers) if workers and workers.isdigit() else None,
        "release": os.environ.get("APP_RELEASE", "Не указана"),
        "git_commit": commit or "Недоступно",
        "started_at": APPLICATION_STARTED_AT,
        "hostname": socket.gethostname(),
    }


def backup_diagnostics() -> dict[str, Any]:
    unavailable = {
        "status": "muted",
        "status_label": "Недоступно",
        "message": "Недоступно в текущем окружении",
        "checked_at": utc_now(),
        "timer_enabled": None,
        "last_run_at": None,
        "last_success": None,
        "last_dump": None,
        "last_dump_size": None,
        "last_dump_at": None,
        "count": None,
        "directory_size": None,
        "next_run": None,
        "dump_verified": None,
        "last_restore_check": None,
    }
    if os.name == "nt" or not shutil.which("systemctl"):
        return unavailable
    result = dict(unavailable)
    enabled = _safe_run(["systemctl", "is-enabled", "key-writer-backup.timer"])
    service_result = _safe_run(
        ["systemctl", "show", "key-writer-backup.service", "--property=Result", "--value"]
    )
    last_run = _safe_run(
        ["systemctl", "show", "key-writer-backup.service", "--property=ExecMainExitTimestamp", "--value"]
    )
    next_run = _safe_run(
        ["systemctl", "show", "key-writer-backup.timer", "--property=NextElapseUSecRealtime", "--value"]
    )
    result.update(
        {
            "timer_enabled": enabled == "enabled",
            "last_run_at": last_run or None,
            "last_success": service_result == "success" if service_result else None,
            "next_run": next_run or None,
        }
    )
    try:
        dumps = sorted(
            (item for item in BACKUP_DIRECTORY.glob("key_writer_*.dump") if item.is_file()),
            key=lambda item: item.stat().st_mtime,
        )
        total_size = sum(item.stat().st_size for item in dumps)
        result["count"] = len(dumps)
        result["directory_size"] = total_size
        if dumps:
            latest = dumps[-1]
            stat = latest.stat()
            result.update(
                {
                    "last_dump": latest.name,
                    "last_dump_size": stat.st_size,
                    "last_dump_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                    # The production script publishes a final file only after
                    # pg_restore --list succeeds.
                    "dump_verified": True,
                }
            )
    except OSError:
        pass
    if not result["timer_enabled"]:
        result.update(status="muted", status_label="Не настроено", message="Backup не настроен")
    elif result["last_success"] and result["last_dump"]:
        result.update(status="ok", status_label="OK", message="Последний backup успешно проверен")
    elif result["last_success"] is False:
        result.update(status="error", status_label="Ошибка", message="Последний запуск backup завершился ошибкой")
    else:
        result.update(status="warning", status_label="Предупреждение", message="Нет подтверждённого успешного backup")
    return result


def security_diagnostics(request_scheme: str) -> dict[str, Any]:
    environment = settings.app_environment.strip().lower()
    warnings: list[str] = []
    if environment == "production" and request_scheme != "https":
        warnings.append("Production открыта по HTTP")
    if environment == "production" and not settings.session_https_only:
        warnings.append("SESSION_HTTPS_ONLY выключен в production")
    status = "warning" if warnings else "ok"
    return {
        "status": status,
        "status_label": "Предупреждение" if warnings else "OK",
        "message": "; ".join(warnings) if warnings else "Параметры транспорта согласованы",
        "checked_at": utc_now(),
        "scheme": request_scheme.upper(),
        "session_https_only": bool(settings.session_https_only),
        "trusted_hosts": settings.trusted_host_list,
        "environment": settings.app_environment,
        "session_secret_ready": (
            settings.session_secret != "change-this-secret-key-later"
            and len(settings.session_secret) >= 32
        ),
        "warnings": warnings,
    }


def format_bytes(value: int | None) -> str:
    if value is None:
        return "Недоступно"
    size = float(value)
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if size < 1024 or unit == "ТБ":
            return f"{size:.1f} {unit}" if unit != "Б" else f"{int(size)} {unit}"
        size /= 1024
    return "Недоступно"


def safe_public_url(value: str) -> str:
    """Return a display URL without embedded username, password or query data."""

    try:
        parsed = urlsplit((value or "").strip())
        if not parsed.scheme or not parsed.hostname:
            return "Не настроено"
        host = parsed.hostname
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        if parsed.port:
            host = f"{host}:{parsed.port}"
    except ValueError:
        return "Некорректный URL"
    return urlunsplit((parsed.scheme, host, parsed.path.rstrip("/"), "", ""))


def connection_status(
    *, configured: bool, last_result: dict[str, Any] | None
) -> dict[str, Any]:
    """Represent external checks without treating configuration as health."""

    if not configured:
        return {
            "status": "muted",
            "status_label": "Не настроено",
            "message": "Обязательные реквизиты не заданы",
            "checked_at": None,
        }
    if not last_result:
        return {
            "status": "warning",
            "status_label": "Предупреждение",
            "message": "Безопасная проверка ещё не выполнялась",
            "checked_at": None,
        }
    return {
        "status": "ok" if last_result.get("ok") else "error",
        "status_label": "OK" if last_result.get("ok") else "Ошибка",
        "message": str(last_result.get("message") or "Результат проверки недоступен"),
        "checked_at": last_result.get("checked_at"),
    }


def overall_status(items: list[dict[str, Any]]) -> dict[str, str]:
    statuses = {str(item.get("status") or "muted") for item in items}
    if "error" in statuses:
        return {
            "status": "error",
            "status_label": "Есть ошибки",
            "message": "Один или несколько компонентов требуют вмешательства",
        }
    if statuses & {"warning", "muted"}:
        return {
            "status": "warning",
            "status_label": "Требует внимания",
            "message": "Система работает, но не все проверки подтверждены",
        }
    return {
        "status": "ok",
        "status_label": "Система исправна",
        "message": "Все доступные проверки завершены успешно",
    }
