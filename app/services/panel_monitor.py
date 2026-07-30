"""One database-coordinated background monitor for all application workers."""

from __future__ import annotations

import logging
import os
import threading
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait

from sqlalchemy import text

from app.db import get_engine
from app.repositories.panel_monitor_repository import (
    begin_cycle_if_due,
    finish_cycle,
    recover_interrupted_cycle,
    set_cycle_total,
    update_cycle_progress,
)
from app.repositories.panel_repository import get_enabled_panels, update_panel_api_status
from app.repositories.system_settings_repository import (
    get_monitor_runtime_settings,
)
from app.services.panel_api import check_panel, panel_api_configured
from app.settings import settings


logger = logging.getLogger(__name__)
ADVISORY_LOCK_ID = 0x4454454C50414E45


def _safe_check(panel: dict, checker) -> dict:
    try:
        result = checker(panel)
        if not isinstance(result, dict) or not result.get("status"):
            raise ValueError("Проверка панели вернула некорректный результат")
        return result
    except Exception as error:  # one device must never stop the complete cycle
        logger.warning("Panel %s monitoring failed: %s", panel.get("id"), type(error).__name__)
        return {
            "status": "error",
            "response_time_ms": None,
            "last_error": "Внутренняя ошибка проверки панели",
        }


def run_monitor_cycle(*, checker=check_panel, concurrency: int | None = None) -> dict:
    """Run one already-claimed cycle and persist progress after every result."""

    runtime = get_monitor_runtime_settings()
    panels = get_enabled_panels(
        runtime.panel_manual_check_cooldown_seconds
    )
    total = len(panels)
    set_cycle_total(total)
    if not panels:
        finish_cycle(completed=0, online=0, failed=0)
        return {"total": 0, "completed": 0, "online": 0, "failed": 0}

    worker_limit = max(
        1,
        min(int(concurrency or runtime.panel_monitor_concurrency), 50, total),
    )
    iterator = iter(panels)
    futures: dict[Future, dict] = {}
    completed = online = failed = 0

    def submit_next(executor: ThreadPoolExecutor) -> bool:
        try:
            panel = next(iterator)
        except StopIteration:
            return False
        futures[executor.submit(_safe_check, panel, checker)] = panel
        return True

    try:
        with ThreadPoolExecutor(
            max_workers=worker_limit,
            thread_name_prefix="panel-monitor-http",
        ) as executor:
            for _ in range(worker_limit):
                if not submit_next(executor):
                    break
            update_cycle_progress(
                completed=0,
                online=0,
                failed=0,
                active_panel_ids=[panel["id"] for panel in futures.values()],
            )

            while futures:
                done, _ = wait(tuple(futures), return_when=FIRST_COMPLETED)
                for future in done:
                    panel = futures.pop(future)
                    result = future.result()
                    update_panel_api_status(panel["id"], result)
                    completed += 1
                    if result.get("status") == "online":
                        online += 1
                    else:
                        failed += 1
                    submit_next(executor)
                update_cycle_progress(
                    completed=completed,
                    online=online,
                    failed=failed,
                    active_panel_ids=[panel["id"] for panel in futures.values()],
                )
    except Exception as error:
        logger.exception("Central panel monitoring cycle failed")
        finish_cycle(
            completed=completed,
            online=online,
            failed=max(failed, total - completed),
            error=f"{type(error).__name__}: цикл мониторинга прерван",
        )
        return {
            "total": total,
            "completed": completed,
            "online": online,
            "failed": max(failed, total - completed),
        }

    finish_cycle(completed=completed, online=online, failed=failed)
    return {
        "total": total,
        "completed": completed,
        "online": online,
        "failed": failed,
    }


class PanelMonitorWorker:
    """Leader-elected scheduler; all web workers may start it safely."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        if not panel_api_configured():
            logger.info("Panel monitor is disabled until panel API credentials are configured")
            return False
        if os.environ.get("TEST_DATABASE_ACTIVE") == "1" and os.environ.get(
            "PANEL_MONITOR_ENABLE_IN_TESTS"
        ) != "1":
            return False
        if self._thread and self._thread.is_alive():
            return False
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="panel-monitor-scheduler",
            daemon=True,
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                with get_engine().connect() as lock_connection:
                    acquired = bool(
                        lock_connection.execute(
                            text("SELECT pg_try_advisory_lock(:lock_id)"),
                            {"lock_id": ADVISORY_LOCK_ID},
                        ).scalar()
                    )
                    if acquired:
                        try:
                            self._leader_loop()
                        finally:
                            lock_connection.execute(
                                text("SELECT pg_advisory_unlock(:lock_id)"),
                                {"lock_id": ADVISORY_LOCK_ID},
                            )
                    else:
                        self._stop.wait(2)
            except Exception:
                logger.exception("Panel monitor leader election failed")
                self._stop.wait(5)

    def _leader_loop(self) -> None:
        while not self._stop.is_set():
            runtime = get_monitor_runtime_settings()
            if not runtime.panel_monitor_enabled:
                self._stop.wait(1)
                continue
            recover_interrupted_cycle(
                max(60, int(settings.panel_api_timeout) * 6),
            )
            cycle = begin_cycle_if_due(
                runtime.panel_monitor_interval_seconds
            )
            if cycle:
                run_monitor_cycle()
            else:
                self._stop.wait(1)


panel_monitor_worker = PanelMonitorWorker()
