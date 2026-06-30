import csv
import io
import re

from openpyxl import load_workbook

from app.db import db
from app.services.panels import split_panel_address


def import_keys_file(filename: str, content: bytes) -> int:
    rows = []

    if filename.lower().endswith(".csv"):
        text = content.decode("utf-8-sig")
        delimiter = ";" if ";" in text.splitlines()[0] else ","

        reader = csv.DictReader(
            io.StringIO(text),
            delimiter=delimiter,
        )

        for row in reader:
            rows.append(row)

    else:
        workbook = load_workbook(
            io.BytesIO(content),
            data_only=True,
        )

        for worksheet in workbook.worksheets:
            headers = [
                str(cell.value or "").strip().lower()
                for cell in next(
                    worksheet.iter_rows(
                        min_row=1,
                        max_row=1,
                    )
                )
            ]

            for row in worksheet.iter_rows(
                min_row=2,
                values_only=True,
            ):
                item = {
                    headers[index]: row[index]
                    for index in range(
                        min(
                            len(headers),
                            len(row),
                        )
                    )
                }

                rows.append(item)

    added = 0

    with db() as conn:
        for row in rows:
            number = str(
                row.get("number")
                or row.get("номер")
                or row.get("printed_number")
                or row.get("напечатанный номер")
                or ""
            ).strip()

            hex_value = str(
                row.get("hex")
                or row.get("hex_value")
                or row.get("код")
                or row.get("код для вшития")
                or ""
            ).strip().upper().replace(" ", "")

            key_type = str(
                row.get("type")
                or row.get("тип")
                or row.get("вид")
                or ""
            ).strip()

            if number and re.fullmatch(r"[0-9A-F]{6,16}", hex_value):
                conn.execute(
                    """
                    INSERT INTO keys(number, hex_value, key_type, updated_at)
                    VALUES(?,?,?,CURRENT_TIMESTAMP)
                    ON CONFLICT(number)
                    DO UPDATE SET
                        hex_value = excluded.hex_value,
                        key_type = excluded.key_type,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        number,
                        hex_value,
                        key_type,
                    ),
                )

                added += 1

    return added


def import_panels_csv(content: bytes) -> int:
    text = content.decode("utf-8-sig")
    delimiter = ";" if ";" in text.splitlines()[0] else ","

    reader = csv.DictReader(
        io.StringIO(text),
        delimiter=delimiter,
    )

    count = 0

    with db() as conn:
        for row in reader:
            address = (
                row.get("address")
                or row.get("адрес")
                or ""
            ).strip()

            mac = (
                row.get("mac")
                or row.get("MAC")
                or ""
            ).strip().upper()

            name = (
                row.get("name")
                or row.get("название")
                or f"{address} {mac}"
            ).strip()

            entrance = (
                row.get("entrance")
                or row.get("вход")
                or row.get("подъезд")
                or ""
            ).strip()

            tags = (
                row.get("tags")
                or row.get("теги")
                or ""
            ).strip()

            if address and mac:
                conn.execute(
                    """
                    INSERT INTO panels(address, entrance, name, mac, tags)
                    VALUES(?,?,?,?,?)
                    ON CONFLICT(mac)
                    DO UPDATE SET
                        address = excluded.address,
                        entrance = excluded.entrance,
                        name = excluded.name,
                        tags = excluded.tags
                    """,
                    (
                        address,
                        entrance,
                        name,
                        mac,
                        tags,
                    ),
                )

                count += 1

    return count


def import_panels_excel(filename: str, content: bytes) -> dict:
    result = {
        "added": 0,
        "updated": 0,
        "skipped": 0,
        "errors": 0,
    }

    if not filename.lower().endswith((".xlsx", ".xlsm", ".xls")):
        result["errors"] += 1
        return result

    workbook = load_workbook(
        io.BytesIO(content),
        data_only=True,
    )

    rows = []

    for worksheet in workbook.worksheets:
        header_row = next(
            worksheet.iter_rows(
                min_row=1,
                max_row=1,
                values_only=True,
            )
        )

        headers = [
            str(header or "").strip().lower()
            for header in header_row
        ]

        address_index = None
        mac_index = None

        for index, header in enumerate(headers):
            if header in ("адрес", "address"):
                address_index = index

            if header in ("mac", "мас", "мак"):
                mac_index = index

        if address_index is None or mac_index is None:
            continue

        for row in worksheet.iter_rows(
            min_row=2,
            values_only=True,
        ):
            raw_address = str(row[address_index] or "").strip()
            raw_mac = str(row[mac_index] or "").strip().upper()

            mac = raw_mac.replace(" ", "")

            if not raw_address or not mac:
                result["skipped"] += 1
                continue

            if not re.fullmatch(r"[0-9A-F]{2}(:[0-9A-F]{2}){5}", mac):
                result["errors"] += 1
                continue

            address, entrance = split_panel_address(raw_address)
            name = f"{address} {entrance}".strip()

            rows.append(
                {
                    "address": address,
                    "entrance": entrance,
                    "name": name,
                    "mac": mac,
                    "tags": "",
                }
            )

    with db() as conn:
        for item in rows:
            existing = conn.execute(
                """
                SELECT *
                FROM panels
                WHERE mac = ?
                """,
                (item["mac"],),
            ).fetchone()

            if existing:
                old = dict(existing)

                changed = (
                    old.get("address") != item["address"]
                    or old.get("entrance") != item["entrance"]
                    or old.get("name") != item["name"]
                )

                conn.execute(
                    """
                    UPDATE panels
                    SET address = ?,
                        entrance = ?,
                        name = ?,
                        tags = ?
                    WHERE mac = ?
                    """,
                    (
                        item["address"],
                        item["entrance"],
                        item["name"],
                        item["tags"],
                        item["mac"],
                    ),
                )

                if changed:
                    result["updated"] += 1
                else:
                    result["skipped"] += 1

            else:
                conn.execute(
                    """
                    INSERT INTO panels(address, entrance, name, mac, tags)
                    VALUES(?,?,?,?,?)
                    """,
                    (
                        item["address"],
                        item["entrance"],
                        item["name"],
                        item["mac"],
                        item["tags"],
                    ),
                )

                result["added"] += 1

    return result