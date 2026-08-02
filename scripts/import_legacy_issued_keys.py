"""Import an old issued-key register without panel or external CRM calls."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from dotenv import dotenv_values
from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.db import get_engine, switch_database
from app.services.legacy_issued_keys import (
    import_legacy_free_keys,
    import_legacy_issued_keys,
    read_legacy_issued_workbook,
)


def _database_url(target: str) -> str:
    values = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
    variable = "TEST_DATABASE_URL" if target == "test" else "DATABASE_URL"
    value = str(os.environ.get(variable) or values.get(variable) or "").strip()
    if not value:
        raise RuntimeError(f"{variable} не задан.")
    return value


def _soffice_path() -> str:
    candidates = (
        shutil.which("soffice"),
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    )
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(candidate)
    raise RuntimeError("Для чтения .xlt требуется LibreOffice (soffice).")


@contextmanager
def _xlsx_source(source: Path):
    if source.suffix.casefold() in {".xlsx", ".xlsm"}:
        yield source
        return
    if source.suffix.casefold() not in {".xlt", ".xls"}:
        raise ValueError("Поддерживаются .xlt, .xls, .xlsx и .xlsm.")

    with tempfile.TemporaryDirectory(prefix="legacy-key-import-") as directory:
        subprocess.run(
            [
                _soffice_path(),
                "--headless",
                "--convert-to",
                "xlsx",
                "--outdir",
                directory,
                str(source),
            ],
            check=True,
            timeout=180,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        converted = Path(directory) / f"{source.stem}.xlsx"
        if not converted.is_file():
            raise RuntimeError("LibreOffice не создал временную XLSX-копию.")
        yield converted


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--target", choices=("test", "production"), default="test")
    parser.add_argument(
        "--mode",
        choices=("issued", "free"),
        default="issued",
        help="issued — ранее выданные с адресом; free — свободные без адреса.",
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--actor", default="Импорт старой базы")
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Не печатать длинные списки ошибок; полный отчёт остаётся в --report.",
    )
    parser.add_argument(
        "--confirm-production",
        default="",
        help="Для записи в production требуется точное значение key_writer.",
    )
    return parser.parse_args()


def _database_snapshot() -> dict:
    result: dict[str, dict] = {}
    with get_engine().connect() as connection:
        for table in ("users", "employees", "panels", "keys", "key_assignments"):
            row = connection.execute(
                text(
                    f"""
                    SELECT
                        COUNT(*) AS row_count,
                        MD5(COALESCE(
                            STRING_AGG(ROW_TO_JSON(source_row)::text, '' ORDER BY id),
                            ''
                        )) AS content_hash
                    FROM {table} AS source_row
                    """
                )
            ).one()
            result[table] = {
                "row_count": int(row[0]),
                "content_hash": str(row[1]),
            }
    return result


def main() -> int:
    args = _parse_args()
    source = args.source.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if (
        args.target == "production"
        and args.apply
        and args.confirm_production != "key_writer"
    ):
        raise RuntimeError(
            "Запись в production требует --confirm-production key_writer."
        )

    url = _database_url(args.target)
    expected_database = "key_writer_test" if args.target == "test" else "key_writer"
    actual_in_url = make_url(url).database
    if actual_in_url != expected_database:
        raise RuntimeError(
            f"Ожидалась база {expected_database}, URL указывает на {actual_in_url}."
        )
    if args.target == "test":
        os.environ["TEST_DATABASE_ACTIVE"] = "1"
    switch_database(url)
    with get_engine().connect() as connection:
        identity = connection.execute(
            text("SELECT current_database(), current_schema()")
        ).one()
    if str(identity[0]) != expected_database:
        raise RuntimeError(
            f"ABORT: current_database()={identity[0]}, ожидалась {expected_database}."
        )
    print(f"DATABASE_CONTEXT database={identity[0]} schema={identity[1]}")
    before_snapshot = _database_snapshot()

    source_hash = sha256(source.read_bytes()).hexdigest()
    with _xlsx_source(source) as workbook_path:
        rows = read_legacy_issued_workbook(workbook_path)
    importer = import_legacy_free_keys if args.mode == "free" else import_legacy_issued_keys
    report = importer(
        rows,
        actor=args.actor,
        dry_run=not args.apply,
        source_name=source.name,
        source_hash=source_hash,
    )
    report["database"] = str(identity[0])
    report["schema"] = str(identity[1])
    report["source"] = source.name
    report["source_sha256"] = source_hash
    report["completed_at"] = datetime.now().astimezone().isoformat()
    after_snapshot = _database_snapshot()
    report["before_snapshot"] = before_snapshot
    report["after_snapshot"] = after_snapshot
    report["protected_tables_unchanged"] = all(
        before_snapshot[table] == after_snapshot[table]
        for table in ("users", "employees", "panels")
    )
    report["assignments_unchanged"] = (
        before_snapshot["key_assignments"] == after_snapshot["key_assignments"]
    )

    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    printable = report
    if args.summary_only:
        printable = {
            key: value
            for key, value in report.items()
            if key not in {
                "error_details",
                "address_details",
                "similar_match_details",
            }
        }
    print(json.dumps(printable, ensure_ascii=False, indent=2))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
