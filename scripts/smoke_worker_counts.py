"""Start the application with several worker counts against key_writer_test.

This is a local deployment smoke check.  It intentionally refuses every
database except the dedicated test database and never enables external-panel
monitoring.
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from sqlalchemy.engine import make_url


REQUIRED_DATABASE = "key_writer_test"
ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _assert_safe_database(value: str) -> None:
    url = make_url(value)
    if url.drivername != "postgresql+psycopg" or url.database != REQUIRED_DATABASE:
        raise SystemExit(
            "SMOKE SAFETY ABORT: TEST_DATABASE_URL must use "
            f"postgresql+psycopg and database {REQUIRED_DATABASE!r}."
        )


def _wait_for_health(port: int, process: subprocess.Popen, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{port}/healthz"
    last_error = "server did not answer"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"uvicorn stopped with exit code {process.returncode}")
        try:
            with urlopen(Request(url, headers={"Host": "testserver"}), timeout=2) as response:
                body = response.read().decode("utf-8")
                if response.status == 200 and '"status":"ok"' in body:
                    return
                last_error = f"HTTP {response.status}: {body[:200]}"
        except (OSError, URLError) as error:
            last_error = str(error)
        time.sleep(0.2)
    raise RuntimeError(f"health check timed out: {last_error}")


def _stop(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def run_worker_smoke(workers: int, database_url: str, timeout: float) -> None:
    port = _free_port()
    environment = os.environ.copy()
    environment.update(
        {
            "DATABASE_URL": database_url,
            "TEST_DATABASE_URL": database_url,
            "TEST_DATABASE_ACTIVE": "1",
            "PANEL_MONITOR_ENABLED": "false",
            "PANEL_MONITOR_ENABLE_IN_TESTS": "0",
            "APP_ENVIRONMENT": "development",
            "TRUSTED_HOSTS": "testserver,localhost,127.0.0.1",
        }
    )
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--workers",
        str(workers),
        "--no-access-log",
    ]
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        _wait_for_health(port, process, timeout)
        print(f"WORKER_SMOKE_OK workers={workers} port={port}")
    except Exception:
        _stop(process)
        output = process.stdout.read() if process.stdout else ""
        raise RuntimeError(output[-4000:])
    else:
        _stop(process)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", nargs="+", type=int, default=[1, 2, 3])
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()

    database_url = os.environ.get("TEST_DATABASE_URL", "").strip()
    if not database_url:
        raise SystemExit("SMOKE SAFETY ABORT: TEST_DATABASE_URL is required.")
    _assert_safe_database(database_url)
    for workers in args.workers:
        if workers < 1 or workers > 8:
            raise SystemExit("Worker smoke count must be between 1 and 8.")
        run_worker_smoke(workers, database_url, args.timeout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
