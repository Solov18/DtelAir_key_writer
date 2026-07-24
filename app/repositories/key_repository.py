import math
import re
from sqlalchemy.exc import IntegrityError

from app.db import db
from app.search_utils import normalize_search_text


KEY_STATUSES = {
    "free": "Свободен",
    "issued_resident": "Выдан жильцу",
    "issued_employee": "Выдан сотруднику",
    "assigned_uk": "Закреплён за УК",
    "blocked": "Заблокирован",
    "lost": "Утерян",
    "defective": "Брак",
    "archived": "Архив",
}

KEY_STATUS_TONES = {
    "free": "success",
    "issued_resident": "info",
    "issued_employee": "purple",
    "assigned_uk": "warning",
    "blocked": "danger",
    "lost": "danger",
    "defective": "warning",
    "archived": "muted",
}

ASSIGNMENT_STATUSES = {
    "resident": "issued_resident",
    "employee": "issued_employee",
    "uk": "assigned_uk",
}


def key_status_name(status: str) -> str:
    return KEY_STATUSES.get(status, status or "—")


def key_status_tone(status: str) -> str:
    return KEY_STATUS_TONES.get(status, "muted")


def _normalize_hex(value: str) -> str:
    value = (value or "").strip().upper()
    return value.replace(" ", "").replace(":", "").replace("-", "")


def _assignment_text(row: dict) -> str:
    assignment_type = row.get("assignment_type") or ""

    if assignment_type == "resident":
        parts = [row.get("assignment_address") or "Жилец"]
        if row.get("assignment_apartment"):
            parts.append(f"кв. {row['assignment_apartment']}")
        return " / ".join(parts)

    if assignment_type == "employee":
        return row.get("employee_name") or "Сотрудник"

    if assignment_type == "uk":
        return row.get("uk_name") or "Управляющая компания"

    return "Свободен"


def _normalize_key_row(row) -> dict:
    item = dict(row)
    item["status_name"] = key_status_name(item.get("status", ""))
    item["status_tone"] = key_status_tone(item.get("status", ""))
    item["assignment_text"] = _assignment_text(item)
    item["has_hex"] = bool(item.get("hex_value"))
    return item


def _key_count_text(value: int) -> str:
    count = int(value or 0)
    if count % 10 == 1 and count % 100 != 11:
        word = "ключ"
    elif count % 10 in {2, 3, 4} and count % 100 not in {12, 13, 14}:
        word = "ключа"
    else:
        word = "ключей"
    return f"{count} {word}"


def get_key_types(include_archived: bool = True) -> list[dict]:
    where = "" if include_archived else "WHERE kt.enabled = 1"

    with db() as conn:
        rows = conn.execute(
            f"""
            SELECT
                kt.*,
                COUNT(k.id) AS keys_count,
                SUM(CASE WHEN k.status = 'free' THEN 1 ELSE 0 END) AS free_count,
                (
                    SELECT k2.number
                    FROM keys k2
                    WHERE k2.key_type_id = kt.id
                      AND TRIM(k2.hex_value) <> ''
                      AND k2.number <> ''
                      AND k2.number NOT GLOB '*[^0-9]*'
                    ORDER BY CAST(k2.number AS INTEGER) DESC,
                             LENGTH(k2.number) DESC,
                             k2.id DESC
                    LIMIT 1
                ) AS last_number
            FROM key_types kt
            LEFT JOIN keys k
                   ON k.key_type_id = kt.id
                  AND TRIM(k.hex_value) <> ''
            {where}
            GROUP BY kt.id
            ORDER BY kt.enabled DESC, kt.name COLLATE NOCASE
            """
        ).fetchall()
        items = [dict(row) for row in rows]

    for item in items:
        last_number = (item.get("last_number") or "").strip()
        item["last_number"] = last_number
        item["keys_count_text"] = _key_count_text(item.get("keys_count", 0))
        item["next_number"] = (
            str(int(last_number) + 1).zfill(len(last_number))
            if last_number.isdigit()
            else ""
        )

    return items


def get_key_type(key_type_id: int) -> dict | None:
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM key_types WHERE id = ?",
            (key_type_id,),
        ).fetchone()
        return dict(row) if row else None


def get_missing_key_numbers(
    key_type_id: int,
    start_number: str = "",
    end_number: str = "",
    limit: int = 500,
) -> dict:
    """Return missing numeric key numbers without expanding huge ranges in memory."""
    key_type = get_key_type(key_type_id)
    if not key_type:
        raise ValueError("Тип ключа не найден.")

    clean_start = (start_number or "").strip()
    clean_end = (end_number or "").strip()
    if clean_start and not re.fullmatch(r"[0-9]+", clean_start):
        raise ValueError("Начало диапазона должно состоять только из цифр.")
    if clean_end and not re.fullmatch(r"[0-9]+", clean_end):
        raise ValueError("Конец диапазона должен состоять только из цифр.")

    with db() as conn:
        rows = conn.execute(
            """
            SELECT number
            FROM keys
            WHERE key_type_id = ?
              AND TRIM(hex_value) <> ''
              AND number <> ''
              AND number NOT GLOB '*[^0-9]*'
            ORDER BY CAST(number AS INTEGER), LENGTH(number), number
            """,
            (key_type_id,),
        ).fetchall()

    stored_numbers = sorted({int(row["number"]) for row in rows})
    if not stored_numbers and not (clean_start and clean_end):
        return {
            "key_type": key_type,
            "start": "",
            "end": "",
            "ranges": [],
            "numbers": [],
            "missing_count": 0,
            "shown_count": 0,
            "truncated": False,
            "empty_type": True,
        }

    start_value = int(clean_start) if clean_start else stored_numbers[0]
    end_value = int(clean_end) if clean_end else stored_numbers[-1]
    if end_value < start_value:
        raise ValueError("Конец диапазона не может быть меньше начала.")
    if end_value - start_value > 10_000_000:
        raise ValueError("Диапазон слишком большой. Уточните начало и конец проверки.")

    width = max(
        len(clean_start),
        len(clean_end),
        max((len(str(row["number"])) for row in rows), default=1),
    )
    present = [
        number
        for number in stored_numbers
        if start_value <= number <= end_value
    ]

    ranges: list[dict] = []
    numbers: list[str] = []
    missing_count = 0
    cursor = start_value

    def add_gap(gap_start: int, gap_end: int) -> None:
        nonlocal missing_count
        if gap_end < gap_start:
            return
        count = gap_end - gap_start + 1
        missing_count += count
        ranges.append(
            {
                "start": str(gap_start).zfill(width),
                "end": str(gap_end).zfill(width),
                "count": count,
            }
        )
        remaining = max(0, limit - len(numbers))
        if remaining:
            numbers.extend(
                str(value).zfill(width)
                for value in range(
                    gap_start,
                    min(gap_end + 1, gap_start + remaining),
                )
            )

    for number in present:
        if number > cursor:
            add_gap(cursor, number - 1)
        cursor = max(cursor, number + 1)
    add_gap(cursor, end_value)

    return {
        "key_type": key_type,
        "start": str(start_value).zfill(width),
        "end": str(end_value).zfill(width),
        "ranges": ranges,
        "numbers": numbers,
        "missing_count": missing_count,
        "shown_count": len(numbers),
        "truncated": missing_count > len(numbers),
        "empty_type": False,
    }


def create_key_type(
    name: str,
    color: str,
    note: str = "",
) -> int:
    clean_name = (name or "").strip()
    clean_color = (color or "#2A9DF4").strip()

    if not clean_name:
        raise ValueError("Укажите название типа ключа.")

    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", clean_color):
        raise ValueError("Цвет должен быть указан в формате #RRGGBB.")

    try:
        with db() as conn:
            cursor = conn.execute(
                """
                INSERT INTO key_types(name, color, note, enabled)
                VALUES (?, ?, ?, 1)
                """,
                (clean_name, clean_color.upper(), (note or "").strip()),
            )
            return int(cursor.lastrowid)
    except IntegrityError as error:
        raise ValueError("Тип ключа с таким названием уже существует.") from error


def update_key_type(
    key_type_id: int,
    name: str,
    color: str,
    note: str,
    enabled: bool,
) -> None:
    clean_name = (name or "").strip()
    clean_color = (color or "#2A9DF4").strip().upper()

    if not clean_name:
        raise ValueError("Укажите название типа ключа.")

    if not re.fullmatch(r"#[0-9A-F]{6}", clean_color):
        raise ValueError("Некорректный цвет типа ключа.")

    try:
        with db() as conn:
            cursor = conn.execute(
                """
                UPDATE key_types
                SET name = ?,
                    color = ?,
                    note = ?,
                    enabled = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    clean_name,
                    clean_color,
                    (note or "").strip(),
                    1 if enabled else 0,
                    key_type_id,
                ),
            )
            if cursor.rowcount == 0:
                raise ValueError("Тип ключа не найден.")

            conn.execute(
                """
                UPDATE keys
                SET key_type = ?, updated_at = CURRENT_TIMESTAMP
                WHERE key_type_id = ?
                """,
                (clean_name, key_type_id),
            )
    except IntegrityError as error:
        raise ValueError("Тип ключа с таким названием уже существует.") from error


def get_key_statistics() -> dict:
    with db() as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN status = 'free' THEN 1 ELSE 0 END) AS free,
                SUM(CASE WHEN status = 'issued_resident' THEN 1 ELSE 0 END) AS residents,
                SUM(CASE WHEN status = 'issued_employee' THEN 1 ELSE 0 END) AS employees,
                SUM(CASE WHEN status = 'assigned_uk' THEN 1 ELSE 0 END) AS uk,
                SUM(CASE WHEN status IN ('blocked', 'lost', 'defective') THEN 1 ELSE 0 END) AS blocked
            FROM keys
            WHERE TRIM(hex_value) <> ''
            """
        ).fetchone()
        return {key: int(value or 0) for key, value in dict(row).items()}


def _keys_filter_sql(
    query: str = "",
    key_type_id: int | None = None,
    status: str = "",
    availability: str = "",
    added_from: str = "",
    added_to: str = "",
    assigned_from: str = "",
    assigned_to: str = "",
) -> tuple[str, list]:
    conditions = ["TRIM(k.hex_value) <> ''"]
    params: list = []

    normalized_query = normalize_search_text(query)
    if normalized_query:
        pattern = f"%{normalized_query}%"
        conditions.append(
            """
            (
                SMART_NORM(k.number) LIKE ?
                OR SMART_NORM(k.hex_value) LIKE ?
                OR SMART_NORM(kt.name) LIKE ?
                OR SMART_NORM(k.note) LIKE ?
                OR SMART_NORM(ka.address) LIKE ?
                OR SMART_NORM(ka.apartment) LIKE ?
                OR SMART_NORM(e.full_name) LIKE ?
                OR SMART_NORM(ug.name) LIKE ?
                OR EXISTS (
                    SELECT 1
                    FROM operation_log ol
                    WHERE ol.key_id = k.id
                      AND (
                          SMART_NORM(ol.address) LIKE ?
                          OR SMART_NORM(ol.apartment) LIKE ?
                          OR SMART_NORM(ol.panel_name) LIKE ?
                          OR SMART_NORM(ol.details) LIKE ?
                          OR SMART_NORM(ol.comment) LIKE ?
                      )
                )
                OR EXISTS (
                    SELECT 1
                    FROM key_assignments kah
                    LEFT JOIN employees eh ON eh.id = kah.employee_id
                    LEFT JOIN uk_groups ugh ON ugh.id = kah.uk_group_id
                    WHERE kah.key_id = k.id
                      AND (
                          SMART_NORM(kah.address) LIKE ?
                          OR SMART_NORM(kah.apartment) LIKE ?
                          OR SMART_NORM(kah.note) LIKE ?
                          OR SMART_NORM(eh.full_name) LIKE ?
                          OR SMART_NORM(ugh.name) LIKE ?
                      )
                )
                OR SMART_NORM(CASE k.status
                    WHEN 'free' THEN 'Свободен'
                    WHEN 'issued_resident' THEN 'Выдан жильцу'
                    WHEN 'issued_employee' THEN 'Выдан сотруднику'
                    WHEN 'assigned_uk' THEN 'Закреплён за УК'
                    WHEN 'blocked' THEN 'Заблокирован'
                    WHEN 'lost' THEN 'Утерян'
                    WHEN 'defective' THEN 'Брак'
                    WHEN 'archived' THEN 'Архив'
                END) LIKE ?
            )
            """
        )
        params.extend([pattern] * 19)

    if key_type_id:
        conditions.append("k.key_type_id = ?")
        params.append(key_type_id)

    if status in KEY_STATUSES:
        conditions.append("k.status = ?")
        params.append(status)

    if availability == "free":
        conditions.append("k.status = 'free'")
    elif availability == "used":
        conditions.append("k.status <> 'free'")

    if added_from:
        conditions.append("substr(k.created_at, 1, 10) >= ?")
        params.append(added_from)

    if added_to:
        conditions.append("substr(k.created_at, 1, 10) <= ?")
        params.append(added_to)

    if assigned_from:
        conditions.append("substr(ka.assigned_at, 1, 10) >= ?")
        params.append(assigned_from)

    if assigned_to:
        conditions.append("substr(ka.assigned_at, 1, 10) <= ?")
        params.append(assigned_to)

    return " AND ".join(conditions), params


def get_keys_page(
    *,
    query: str = "",
    key_type_id: int | None = None,
    status: str = "",
    availability: str = "",
    added_from: str = "",
    added_to: str = "",
    assigned_from: str = "",
    assigned_to: str = "",
    page: int = 1,
    page_size: int = 50,
) -> dict:
    page = max(1, int(page or 1))
    page_size = min(200, max(20, int(page_size or 50)))
    where_sql, params = _keys_filter_sql(
        query,
        key_type_id,
        status,
        availability,
        added_from,
        added_to,
        assigned_from,
        assigned_to,
    )

    joins = """
        JOIN key_types kt ON kt.id = k.key_type_id
        LEFT JOIN key_assignments ka ON ka.key_id = k.id AND ka.active = 1
        LEFT JOIN employees e ON e.id = ka.employee_id
        LEFT JOIN uk_groups ug ON ug.id = ka.uk_group_id
    """

    with db() as conn:
        total = int(
            conn.execute(
                f"SELECT COUNT(*) FROM keys k {joins} WHERE {where_sql}",
                params,
            ).fetchone()[0]
        )
        pages = max(1, math.ceil(total / page_size))
        page = min(page, pages)
        offset = (page - 1) * page_size
        rows = conn.execute(
            f"""
            SELECT
                k.*,
                kt.name AS type_name,
                kt.color AS type_color,
                kt.enabled AS type_enabled,
                ka.assignment_type,
                ka.address AS assignment_address,
                ka.apartment AS assignment_apartment,
                ka.assigned_at,
                e.full_name AS employee_name,
                ug.name AS uk_name
            FROM keys k
            {joins}
            WHERE {where_sql}
            ORDER BY k.id DESC
            LIMIT ? OFFSET ?
            """,
            [*params, page_size, offset],
        ).fetchall()

    return {
        "items": [_normalize_key_row(row) for row in rows],
        "total": total,
        "page": page,
        "pages": pages,
        "page_size": page_size,
    }


def get_recent_keys(limit: int = 300) -> list[dict]:
    return get_keys_page(page_size=min(limit, 200))["items"]


def get_key(key_id: int) -> dict | None:
    with db() as conn:
        row = conn.execute(
            """
            SELECT
                k.*,
                kt.name AS type_name,
                kt.color AS type_color,
                kt.enabled AS type_enabled,
                ka.id AS assignment_id,
                ka.assignment_type,
                ka.address AS assignment_address,
                ka.apartment AS assignment_apartment,
                ka.assigned_at,
                ka.assigned_by,
                ka.note AS assignment_note,
                e.full_name AS employee_name,
                ug.name AS uk_name
            FROM keys k
            JOIN key_types kt ON kt.id = k.key_type_id
            LEFT JOIN key_assignments ka ON ka.key_id = k.id AND ka.active = 1
            LEFT JOIN employees e ON e.id = ka.employee_id
            LEFT JOIN uk_groups ug ON ug.id = ka.uk_group_id
            WHERE k.id = ?
            """,
            (key_id,),
        ).fetchone()
        return _normalize_key_row(row) if row else None


def get_key_history(key_id: int, limit: int = 200) -> list[dict]:
    key = get_key(key_id)
    if not key:
        return []

    with db() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM operation_log
            WHERE key_id = ?
               OR (
                    key_id IS NULL
                    AND printed_number = ?
                    AND UPPER(hex_value) = UPPER(?)
               )
            ORDER BY id DESC
            LIMIT ?
            """,
            (key_id, key["number"], key["hex_value"], limit),
        ).fetchall()
        return [dict(row) for row in rows]


def get_key_assignments(key_id: int) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT
                ka.*,
                e.full_name AS employee_name,
                ug.name AS uk_name
            FROM key_assignments ka
            LEFT JOIN employees e ON e.id = ka.employee_id
            LEFT JOIN uk_groups ug ON ug.id = ka.uk_group_id
            WHERE ka.key_id = ?
            ORDER BY ka.active DESC, ka.id DESC
            """,
            (key_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def prepare_key_range(
    key_type_id: int,
    start_number: int | str,
    count: int,
    created_by: str,
) -> dict:
    start_text = str(start_number).strip()
    if not re.fullmatch(r"[0-9]+", start_text):
        raise ValueError("Начальный номер должен состоять только из цифр.")
    if count < 1 or count > 1000:
        raise ValueError("За один раз можно подготовить от 1 до 1000 ключей.")

    start_value = int(start_text)
    number_width = len(start_text)
    numbers = [
        str(number).zfill(number_width)
        for number in range(start_value, start_value + count)
    ]

    key_type = get_key_type(key_type_id)
    if not key_type or not key_type.get("enabled"):
        raise ValueError("Выберите активный тип ключа.")

    number_placeholders = ",".join("?" for _ in numbers)
    with db() as conn:
        rows = conn.execute(
            f"""
            SELECT k.*, kt.name AS type_name, kt.color AS type_color
            FROM keys k
            JOIN key_types kt ON kt.id = k.key_type_id
            WHERE k.key_type_id = ?
              AND k.number IN ({number_placeholders})
            ORDER BY LENGTH(k.number), k.number
            """,
            (key_type_id, *numbers),
        ).fetchall()

    existing_by_number = {
        str(row["number"]): dict(row)
        for row in rows
    }
    filled_rows = [
        row
        for row in existing_by_number.values()
        if (row.get("hex_value") or "").strip()
    ]
    pending_rows = []
    legacy_placeholders = 0
    for number in numbers:
        existing_row = existing_by_number.get(number)
        if existing_row and (existing_row.get("hex_value") or "").strip():
            continue
        if existing_row:
            legacy_placeholders += 1
        pending_rows.append(
            {
                "number": number,
                "key_type_id": key_type_id,
                "type_name": key_type["name"],
                "type_color": key_type["color"],
            }
        )

    return {
        "created": 0,
        "existing": len(existing_by_number),
        "requested": count,
        "resumed": legacy_placeholders,
        "filled_existing": len(filled_rows),
        "filled_rows": filled_rows,
        "rows": pending_rows,
        "key_type": key_type,
        "start": numbers[0],
        "end": numbers[-1],
        "count": count,
    }


def save_prepared_key(
    key_type_id: int,
    number: str,
    hex_value: str,
    username: str = "",
    allow_replace: bool = False,
) -> dict:
    clean_number = (number or "").strip()
    clean_hex = _normalize_hex(hex_value)

    if not re.fullmatch(r"[0-9]+", clean_number):
        raise ValueError("Номер подготовленного ключа должен состоять только из цифр.")
    if not re.fullmatch(r"[0-9A-F]{6,16}", clean_hex):
        raise ValueError("HEX должен содержать от 6 до 16 символов 0-9/A-F.")

    key_type = get_key_type(key_type_id)
    if not key_type or not key_type.get("enabled"):
        raise ValueError("Выберите активный тип ключа.")

    with db() as conn:
        existing = conn.execute(
            """
            SELECT id, hex_value
            FROM keys
            WHERE key_type_id = ? AND number = ? COLLATE NOCASE
            LIMIT 1
            """,
            (key_type_id, clean_number),
        ).fetchone()
        existing_id = int(existing["id"]) if existing else None
        current_hex = _normalize_hex(existing["hex_value"] or "") if existing else ""

        if current_hex and current_hex != clean_hex and not allow_replace:
            raise ValueError(
                "У этого номера уже сохранён HEX. Нажмите «Исправить», чтобы заменить его осознанно."
            )

        duplicate = conn.execute(
            """
            SELECT k.id, k.number, kt.name AS type_name
            FROM keys k
            JOIN key_types kt ON kt.id = k.key_type_id
            WHERE UPPER(k.hex_value) = ?
              AND (? IS NULL OR k.id <> ?)
            LIMIT 1
            """,
            (clean_hex, existing_id, existing_id),
        ).fetchone()
        if duplicate:
            raise ValueError(
                f"HEX уже принадлежит ключу {duplicate['type_name']} №{duplicate['number']}."
            )

        if existing:
            conn.execute(
                """
                UPDATE keys
                SET hex_value = ?,
                    key_type = ?,
                    updated_at = CURRENT_TIMESTAMP,
                    created_by = CASE WHEN created_by = '' THEN ? ELSE created_by END
                WHERE id = ?
                """,
                (clean_hex, key_type["name"], username, existing_id),
            )
            key_id = existing_id
        else:
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO keys(
                        key_type_id,
                        number,
                        hex_value,
                        key_type,
                        status,
                        created_by
                    )
                    VALUES (?, ?, ?, ?, 'free', ?)
                    """,
                    (
                        key_type_id,
                        clean_number,
                        clean_hex,
                        key_type["name"],
                        username,
                    ),
                )
            except IntegrityError as error:
                raise ValueError(
                    "Номер или HEX уже был сохранён другим оператором. Обновите партию и повторите проверку."
                ) from error
            key_id = int(cursor.lastrowid)

    key = get_key(key_id)
    if not key:
        raise ValueError("Ключ не найден после сохранения.")
    return key


def save_key_hex(
    key_id: int,
    hex_value: str,
    username: str = "",
    allow_replace: bool = False,
) -> dict:
    clean_hex = _normalize_hex(hex_value)

    if not re.fullmatch(r"[0-9A-F]{6,16}", clean_hex):
        raise ValueError("HEX должен содержать от 6 до 16 символов 0-9/A-F.")

    with db() as conn:
        current = conn.execute(
            "SELECT id, hex_value FROM keys WHERE id = ?",
            (key_id,),
        ).fetchone()
        if not current:
            raise ValueError("Ключ не найден.")

        current_hex = _normalize_hex(current["hex_value"] or "")
        if current_hex and current_hex != clean_hex and not allow_replace:
            raise ValueError(
                "HEX уже сохранён. Нажмите «Исправить», чтобы заменить его осознанно."
            )

        duplicate = conn.execute(
            """
            SELECT k.id, k.number, kt.name AS type_name
            FROM keys k
            JOIN key_types kt ON kt.id = k.key_type_id
            WHERE UPPER(k.hex_value) = ? AND k.id <> ?
            LIMIT 1
            """,
            (clean_hex, key_id),
        ).fetchone()
        if duplicate:
            raise ValueError(
                f"HEX уже принадлежит ключу {duplicate['type_name']} №{duplicate['number']}."
            )

        cursor = conn.execute(
            """
            UPDATE keys
            SET hex_value = ?,
                updated_at = CURRENT_TIMESTAMP,
                created_by = CASE WHEN created_by = '' THEN ? ELSE created_by END
            WHERE id = ?
            """,
            (clean_hex, username, key_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("Ключ не найден.")

    key = get_key(key_id)
    if not key:
        raise ValueError("Ключ не найден.")
    return key


def update_key(
    key_id: int,
    key_type_id: int,
    number: str,
    hex_value: str,
    note: str,
) -> None:
    clean_number = (number or "").strip()
    clean_hex = _normalize_hex(hex_value)

    if not clean_number:
        raise ValueError("Укажите номер ключа.")
    if not clean_hex:
        raise ValueError("Ключ нельзя сохранить без HEX.")
    if not re.fullmatch(r"[0-9A-F]{6,16}", clean_hex):
        raise ValueError("Некорректный HEX ключа.")
    key_type = get_key_type(key_type_id)
    if not key_type:
        raise ValueError("Тип ключа не найден.")

    with db() as conn:
        duplicate = conn.execute(
            "SELECT id FROM keys WHERE UPPER(hex_value) = ? AND id <> ? LIMIT 1",
            (clean_hex, key_id),
        ).fetchone()
        if duplicate:
            raise ValueError("Такой HEX уже используется другим ключом.")

        try:
            cursor = conn.execute(
                """
                UPDATE keys
                SET key_type_id = ?,
                    key_type = ?,
                    number = ?,
                    hex_value = ?,
                    note = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    key_type_id,
                    key_type["name"],
                    clean_number,
                    clean_hex,
                    (note or "").strip(),
                    key_id,
                ),
            )
        except IntegrityError as error:
            raise ValueError("Ключ с таким номером уже есть в выбранном типе.") from error

        if cursor.rowcount == 0:
            raise ValueError("Ключ не найден.")


def set_key_assignment_on_connection(
    conn,
    key_id: int,
    assignment_type: str,
    *,
    address: str = "",
    apartment: str = "",
    employee_id: int | None = None,
    uk_group_id: int | None = None,
    assigned_by: str = "",
    note: str = "",
) -> None:
    if assignment_type not in ASSIGNMENT_STATUSES:
        raise ValueError("Некорректный тип назначения ключа.")

    stored_key = conn.execute(
        "SELECT hex_value FROM keys WHERE id = ?",
        (key_id,),
    ).fetchone()
    if not stored_key:
        raise ValueError("Ключ не найден.")
    if not (stored_key["hex_value"] or "").strip():
        raise ValueError("Ключ без HEX нельзя назначить.")

    # Синхронизируем старые разделы сотрудников и УК с единым текущим
    # назначением. Иначе один физический ключ продолжал отображаться сразу
    # в нескольких местах после переноса.
    if assignment_type != "employee":
        conn.execute(
            """
            UPDATE employee_keys
            SET status = 'replaced',
                closed_at = CURRENT_TIMESTAMP,
                close_reason = 'Ключ переназначен',
                updated_at = CURRENT_TIMESTAMP
            WHERE key_id = ? AND status = 'active'
            """,
            (key_id,),
        )

    if assignment_type == "uk" and uk_group_id:
        conn.execute(
            "DELETE FROM uk_group_keys WHERE key_id = ? AND group_id <> ?",
            (key_id, uk_group_id),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO uk_group_keys(group_id, key_id)
            VALUES (?, ?)
            """,
            (uk_group_id, key_id),
        )
    else:
        conn.execute(
            "DELETE FROM uk_group_keys WHERE key_id = ?",
            (key_id,),
        )

    current = conn.execute(
        """
        SELECT *
        FROM key_assignments
        WHERE key_id = ? AND active = 1
        LIMIT 1
        """,
        (key_id,),
    ).fetchone()

    same_assignment = bool(
        current
        and current["assignment_type"] == assignment_type
        and (
            assignment_type == "employee"
            and current["employee_id"] == employee_id
            or assignment_type == "uk"
            and current["uk_group_id"] == uk_group_id
            or assignment_type == "resident"
            and (current["address"] or "").strip().lower() == (address or "").strip().lower()
            and (current["apartment"] or "").strip().lower() == (apartment or "").strip().lower()
        )
    )

    if same_assignment:
        conn.execute(
            """
            UPDATE key_assignments
            SET address = CASE WHEN ? <> '' THEN ? ELSE address END,
                apartment = CASE WHEN ? <> '' THEN ? ELSE apartment END,
                assigned_by = CASE WHEN ? <> '' THEN ? ELSE assigned_by END,
                note = CASE WHEN ? <> '' THEN ? ELSE note END
            WHERE id = ?
            """,
            (
                (address or "").strip(),
                (address or "").strip(),
                (apartment or "").strip(),
                (apartment or "").strip(),
                assigned_by,
                assigned_by,
                (note or "").strip(),
                (note or "").strip(),
                current["id"],
            ),
        )
        conn.execute(
            """
            UPDATE keys
            SET status = ?, is_used = 1, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (ASSIGNMENT_STATUSES[assignment_type], key_id),
        )
        return

    conn.execute(
        """
        UPDATE key_assignments
        SET active = 0,
            released_at = CURRENT_TIMESTAMP
        WHERE key_id = ? AND active = 1
        """,
        (key_id,),
    )
    conn.execute(
        """
        INSERT INTO key_assignments(
            key_id,
            assignment_type,
            address,
            apartment,
            employee_id,
            uk_group_id,
            assigned_by,
            active,
            note
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
        """,
        (
            key_id,
            assignment_type,
            (address or "").strip(),
            (apartment or "").strip(),
            employee_id,
            uk_group_id,
            assigned_by,
            (note or "").strip(),
        ),
    )
    conn.execute(
        """
        UPDATE keys
        SET status = ?, is_used = 1, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (ASSIGNMENT_STATUSES[assignment_type], key_id),
    )


def set_key_assignment(
    key_id: int,
    assignment_type: str,
    *,
    address: str = "",
    apartment: str = "",
    employee_id: int | None = None,
    uk_group_id: int | None = None,
    assigned_by: str = "",
    note: str = "",
) -> None:
    with db() as conn:
        set_key_assignment_on_connection(
            conn,
            key_id,
            assignment_type,
            address=address,
            apartment=apartment,
            employee_id=employee_id,
            uk_group_id=uk_group_id,
            assigned_by=assigned_by,
            note=note,
        )


def release_key_on_connection(conn, key_id: int, note: str = "") -> None:
    conn.execute(
        """
        UPDATE employee_keys
        SET status = 'inactive',
            closed_at = CURRENT_TIMESTAMP,
            close_reason = CASE WHEN ? <> '' THEN ? ELSE 'Ключ освобождён' END,
            updated_at = CURRENT_TIMESTAMP
        WHERE key_id = ? AND status = 'active'
        """,
        ((note or "").strip(), (note or "").strip(), key_id),
    )
    conn.execute(
        "DELETE FROM uk_group_keys WHERE key_id = ?",
        (key_id,),
    )
    conn.execute(
        """
        UPDATE key_assignments
        SET active = 0,
            released_at = CURRENT_TIMESTAMP,
            note = CASE WHEN ? <> '' THEN ? ELSE note END
        WHERE key_id = ? AND active = 1
        """,
        ((note or "").strip(), (note or "").strip(), key_id),
    )
    cursor = conn.execute(
        """
        UPDATE keys
        SET status = 'free', is_used = 0, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (key_id,),
    )
    if cursor.rowcount == 0:
        raise ValueError("Ключ не найден.")


def release_key(key_id: int, note: str = "") -> None:
    with db() as conn:
        release_key_on_connection(conn, key_id, note)


def set_key_status(key_id: int, status: str, note: str = "") -> None:
    if status not in KEY_STATUSES:
        raise ValueError("Некорректный статус ключа.")

    if status == "free":
        release_key(key_id, note)
        return

    with db() as conn:
        if status in {"blocked", "lost", "defective", "archived"}:
            release_key_on_connection(conn, key_id, note)
        cursor = conn.execute(
            """
            UPDATE keys
            SET status = ?,
                is_used = CASE WHEN ? = 'free' THEN 0 ELSE is_used END,
                note = CASE WHEN ? <> '' THEN ? ELSE note END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (status, status, (note or "").strip(), (note or "").strip(), key_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("Ключ не найден.")


def get_all_keys_for_export() -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT
                k.id,
                kt.name AS type_name,
                k.number,
                k.hex_value,
                k.status,
                k.note,
                k.created_at,
                k.updated_at,
                k.created_by
            FROM keys k
            JOIN key_types kt ON kt.id = k.key_type_id
            WHERE TRIM(k.hex_value) <> ''
            ORDER BY kt.name COLLATE NOCASE, LENGTH(k.number), k.number
            """
        ).fetchall()
        return [dict(row) for row in rows]
