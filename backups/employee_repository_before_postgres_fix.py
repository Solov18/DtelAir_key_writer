import math

from app.db import db
from app.repositories.key_repository import (
    release_key_on_connection,
    set_key_assignment_on_connection,
)
from app.search_utils import normalize_search_text


ACTIVE_KEY_STATUS = "active"

CLOSED_KEY_STATUSES = {
    "replaced",
    "lost",
    "damaged",
    "dismissed",
    "inactive",
}


def _employee_card_query(enabled: int) -> str:
    return """
        SELECT
            e.*,
            (
                SELECT COUNT(*)
                FROM employee_keys active_count
                WHERE active_count.employee_id = e.id
                  AND active_count.status = 'active'
            ) AS active_key_count,
            (
                SELECT GROUP_CONCAT(number, ' · ')
                FROM (
                    SELECT active_key.number AS number
                    FROM employee_keys active_ek
                    JOIN keys active_key ON active_key.id = active_ek.key_id
                    WHERE active_ek.employee_id = e.id
                      AND active_ek.status = 'active'
                    ORDER BY datetime(active_ek.issued_at) DESC, active_ek.id DESC
                )
            ) AS active_key_numbers,
            (
                SELECT active_key.number
                FROM employee_keys active_ek
                JOIN keys active_key ON active_key.id = active_ek.key_id
                WHERE active_ek.employee_id = e.id
                  AND active_ek.status = 'active'
                ORDER BY datetime(active_ek.issued_at) DESC, active_ek.id DESC
                LIMIT 1
            ) AS active_key_number,
            (
                SELECT active_ek.comment
                FROM employee_keys active_ek
                WHERE active_ek.employee_id = e.id
                  AND active_ek.status = 'active'
                ORDER BY datetime(active_ek.issued_at) DESC, active_ek.id DESC
                LIMIT 1
            ) AS active_key_comment,

            (
                SELECT COUNT(*)
                FROM employee_keys history_ek
                WHERE history_ek.employee_id = e.id
                  AND history_ek.status <> 'active'
            ) AS history_count,

            (
                SELECT k.number
                FROM employee_keys last_ek
                JOIN keys k ON k.id = last_ek.key_id
                WHERE last_ek.employee_id = e.id
                ORDER BY
                    datetime(COALESCE(last_ek.closed_at, last_ek.updated_at, last_ek.created_at)) DESC,
                    last_ek.id DESC
                LIMIT 1
            ) AS last_key_number

        FROM employees e
        WHERE e.enabled = ?
        ORDER BY e.full_name COLLATE NOCASE
    """


def get_active_employees() -> list[dict]:
    with db() as conn:
        rows = conn.execute(_employee_card_query(1), (1,)).fetchall()
        return [dict(row) for row in rows]


def get_dismissed_employees() -> list[dict]:
    with db() as conn:
        rows = conn.execute(_employee_card_query(0), (0,)).fetchall()
        return [dict(row) for row in rows]


def get_employee(employee_id: int) -> dict | None:
    with db() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM employees
            WHERE id = ?
              AND enabled = 1
            """,
            (employee_id,),
        ).fetchone()

        return dict(row) if row else None


def get_employee_any_status(employee_id: int) -> dict | None:
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM employees WHERE id = ?",
            (employee_id,),
        ).fetchone()

        return dict(row) if row else None


def get_employee_by_name(full_name: str) -> dict | None:
    normalized_name = full_name.strip()

    if not normalized_name:
        return None

    with db() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM employees
            WHERE enabled = 1
              AND full_name = ? COLLATE NOCASE
            LIMIT 1
            """,
            (normalized_name,),
        ).fetchone()

        return dict(row) if row else None


def get_employees_count() -> int:
    with db() as conn:
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM employees WHERE enabled = 1"
            ).fetchone()[0]
        )


def get_dismissed_employees_count() -> int:
    with db() as conn:
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM employees WHERE enabled = 0"
            ).fetchone()[0]
        )


def get_employee_keys_count() -> int:
    with db() as conn:
        return int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM employee_keys ek
                JOIN employees e ON e.id = ek.employee_id
                WHERE e.enabled = 1
                  AND ek.status = 'active'
                """
            ).fetchone()[0]
        )


def get_employee_statistics() -> dict:
    with db() as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN enabled = 1 THEN 1 ELSE 0 END) AS active,
                SUM(CASE WHEN enabled = 0 THEN 1 ELSE 0 END) AS dismissed,
                SUM(
                    CASE WHEN enabled = 1 AND EXISTS (
                        SELECT 1 FROM employee_keys ek
                        WHERE ek.employee_id = employees.id
                          AND ek.status = 'active'
                    ) THEN 1 ELSE 0 END
                ) AS with_keys,
                SUM(
                    CASE WHEN enabled = 1 AND NOT EXISTS (
                        SELECT 1 FROM employee_keys ek
                        WHERE ek.employee_id = employees.id
                          AND ek.status = 'active'
                    ) THEN 1 ELSE 0 END
                ) AS without_keys
            FROM employees
            """
        ).fetchone()
    return {
        key: int(value or 0)
        for key, value in dict(row).items()
    }


def get_employee_filter_options() -> dict:
    with db() as conn:
        departments = [
            row[0]
            for row in conn.execute(
                """
                SELECT DISTINCT department
                FROM employees
                WHERE enabled = 1 AND TRIM(department) <> ''
                ORDER BY department COLLATE NOCASE
                """
            )
        ]
        positions = [
            row[0]
            for row in conn.execute(
                """
                SELECT DISTINCT position
                FROM employees
                WHERE enabled = 1 AND TRIM(position) <> ''
                ORDER BY position COLLATE NOCASE
                """
            )
        ]
    return {"departments": departments, "positions": positions}


def get_employee_page(
    *,
    enabled: bool = True,
    query: str = "",
    key_status: str = "",
    department: str = "",
    position: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict:
    conditions = ["e.enabled = ?"]
    params: list = [1 if enabled else 0]
    normalized_query = normalize_search_text(query)

    if normalized_query:
        pattern = f"%{normalized_query}%"
        conditions.append(
            """
            (
                SMART_NORM(e.full_name) LIKE ?
                OR SMART_NORM(e.position) LIKE ?
                OR SMART_NORM(e.department) LIKE ?
                OR SMART_NORM(e.phone) LIKE ?
                OR SMART_NORM(e.email) LIKE ?
                OR SMART_NORM(e.note) LIKE ?
                OR EXISTS (
                    SELECT 1
                    FROM employee_keys search_ek
                    JOIN keys search_key ON search_key.id = search_ek.key_id
                    WHERE search_ek.employee_id = e.id
                      AND (
                          SMART_NORM(search_key.number) LIKE ?
                          OR SMART_NORM(search_key.hex_value) LIKE ?
                          OR SMART_NORM(search_key.key_type) LIKE ?
                      )
                )
            )
            """
        )
        params.extend([pattern] * 9)

    if department:
        conditions.append("e.department = ?")
        params.append(department)
    if position:
        conditions.append("e.position = ?")
        params.append(position)
    if key_status == "with_keys":
        conditions.append(
            """
            EXISTS (
                SELECT 1 FROM employee_keys status_ek
                WHERE status_ek.employee_id = e.id
                  AND status_ek.status = 'active'
            )
            """
        )
    elif key_status == "without_keys":
        conditions.append(
            """
            NOT EXISTS (
                SELECT 1 FROM employee_keys status_ek
                WHERE status_ek.employee_id = e.id
                  AND status_ek.status = 'active'
            )
            """
        )

    where_sql = " AND ".join(conditions)
    page = max(1, int(page or 1))
    page_size = min(100, max(10, int(page_size or 20)))

    select_sql = _employee_card_query(1).replace(
        "WHERE e.enabled = ?\n        ORDER BY e.full_name COLLATE NOCASE",
        f"WHERE {where_sql}\n        ORDER BY e.full_name COLLATE NOCASE",
    )

    with db() as conn:
        total = int(
            conn.execute(
                f"SELECT COUNT(*) FROM employees e WHERE {where_sql}",
                params,
            ).fetchone()[0]
        )
        pages = max(1, math.ceil(total / page_size))
        page = min(page, pages)
        rows = conn.execute(
            f"{select_sql.rstrip()} LIMIT ? OFFSET ?",
            [*params, page_size, (page - 1) * page_size],
        ).fetchall()

    return {
        "items": [dict(row) for row in rows],
        "total": total,
        "page": page,
        "pages": pages,
        "page_size": page_size,
    }


def create_employee(
    full_name: str,
    note: str = "",
    position: str = "",
    department: str = "",
    phone: str = "",
    email: str = "",
    created_by: str = "",
) -> int:
    normalized_name = full_name.strip()

    if not normalized_name:
        raise ValueError("Не указано ФИО сотрудника.")

    with db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO employees(
                full_name,
                note,
                position,
                department,
                phone,
                email,
                created_by,
                enabled,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (
                normalized_name,
                note.strip(),
                position.strip(),
                department.strip(),
                phone.strip(),
                email.strip(),
                created_by.strip(),
            ),
        )

        return int(cursor.lastrowid)


def update_employee(
    employee_id: int,
    full_name: str,
    note: str = "",
    position: str = "",
    department: str = "",
    phone: str = "",
    email: str = "",
) -> None:
    normalized_name = full_name.strip()

    if not normalized_name:
        raise ValueError("Не указано ФИО сотрудника.")

    with db() as conn:
        cursor = conn.execute(
            """
            UPDATE employees
            SET
                full_name = ?,
                note = ?,
                position = ?,
                department = ?,
                phone = ?,
                email = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND enabled = 1
            """,
            (
                normalized_name,
                note.strip(),
                position.strip(),
                department.strip(),
                phone.strip(),
                email.strip(),
                employee_id,
            ),
        )

        if cursor.rowcount == 0:
            raise ValueError("Сотрудник не найден.")


def restore_employee(employee_id: int) -> None:
    with db() as conn:
        cursor = conn.execute(
            """
            UPDATE employees
            SET
                enabled = 1,
                dismissed_at = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND enabled = 0
            """,
            (employee_id,),
        )

        if cursor.rowcount == 0:
            raise ValueError("Уволенный сотрудник не найден.")


def get_employee_active_keys(employee_id: int) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT
                ek.id AS assignment_id,
                ek.employee_id,
                ek.key_id,
                ek.status,
                ek.issued_at,
                ek.closed_at,
                ek.close_reason,
                ek.comment,
                ek.created_at,
                ek.updated_at,

                k.number,
                k.hex_value,
                k.key_type,
                k.note AS key_note,
                COALESCE(kt.color, '#2A9DF4') AS key_type_color

            FROM employee_keys ek
            JOIN keys k ON k.id = ek.key_id
            LEFT JOIN key_types kt ON kt.id = k.key_type_id

            WHERE ek.employee_id = ?
              AND ek.status = 'active'
            ORDER BY datetime(ek.issued_at) DESC, ek.id DESC
            """,
            (employee_id,),
        ).fetchall()

        return [dict(row) for row in rows]


def get_employee_active_key(employee_id: int) -> dict | None:
    keys = get_employee_active_keys(employee_id)
    return keys[0] if keys else None


def get_employee_key_history(employee_id: int) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT
                ek.id AS assignment_id,
                ek.employee_id,
                ek.key_id,
                ek.status,
                ek.issued_at,
                ek.closed_at,
                ek.close_reason,
                ek.comment,
                ek.created_at,
                ek.updated_at,

                k.number,
                k.hex_value,
                k.key_type,
                k.note AS key_note

            FROM employee_keys ek
            JOIN keys k ON k.id = ek.key_id

            WHERE ek.employee_id = ?
              AND ek.status <> 'active'

            ORDER BY
                datetime(COALESCE(ek.closed_at, ek.updated_at, ek.created_at)) DESC,
                ek.id DESC
            """,
            (employee_id,),
        ).fetchall()

        return [dict(row) for row in rows]


def get_employee_keys(employee_id: int) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT
                ek.id AS assignment_id,
                ek.employee_id,
                ek.key_id,
                ek.status,
                ek.issued_at,
                ek.closed_at,
                ek.close_reason,
                ek.comment,
                ek.created_at,
                ek.updated_at,

                k.id,
                k.number,
                k.hex_value,
                k.key_type,
                k.note AS key_note

            FROM employee_keys ek
            JOIN keys k ON k.id = ek.key_id
            WHERE ek.employee_id = ?

            ORDER BY
                CASE WHEN ek.status = 'active' THEN 0 ELSE 1 END,
                datetime(ek.issued_at) DESC,
                ek.id DESC
            """,
            (employee_id,),
        ).fetchall()

        return [dict(row) for row in rows]


def issue_key_to_employee(
    employee_id: int,
    key_id: int,
    new_key_comment: str = "",
    old_key_status: str = "replaced",
    old_key_reason: str = "Выдан новый ключ",
    old_key_comment: str = "",
) -> int:
    if old_key_status not in CLOSED_KEY_STATUSES:
        raise ValueError("Недопустимый статус старого ключа.")

    with db() as conn:
        employee = conn.execute(
            """
            SELECT id
            FROM employees
            WHERE id = ? AND enabled = 1
            """,
            (employee_id,),
        ).fetchone()

        if not employee:
            raise ValueError("Сотрудник не найден или уже уволен.")

        key = conn.execute(
            "SELECT id, hex_value FROM keys WHERE id = ?",
            (key_id,),
        ).fetchone()

        if not key:
            raise ValueError("Ключ не найден.")
        if not (key["hex_value"] or "").strip():
            raise ValueError("Ключ без HEX нельзя выдать сотруднику.")

        key_owner = conn.execute(
            """
            SELECT e.full_name
            FROM employee_keys ek
            JOIN employees e ON e.id = ek.employee_id
            WHERE ek.key_id = ?
              AND ek.status = 'active'
              AND ek.employee_id <> ?
            LIMIT 1
            """,
            (key_id, employee_id),
        ).fetchone()

        if key_owner:
            raise ValueError(
                f"Ключ уже используется сотрудником: {key_owner['full_name']}."
            )

        current_assignment = conn.execute(
            """
            SELECT id, key_id
            FROM employee_keys
            WHERE employee_id = ?
              AND key_id = ?
              AND status = 'active'
            LIMIT 1
            """,
            (employee_id, key_id),
        ).fetchone()

        if current_assignment:
            conn.execute(
                """
                UPDATE employee_keys
                SET
                    comment = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (new_key_comment.strip(), current_assignment["id"]),
            )
            return int(current_assignment["id"])

        previous_assignment = conn.execute(
            """
            SELECT id
            FROM employee_keys
            WHERE employee_id = ?
              AND key_id = ?
            LIMIT 1
            """,
            (employee_id, key_id),
        ).fetchone()

        if previous_assignment:
            conn.execute(
                """
                UPDATE employee_keys
                SET
                    status = 'active',
                    issued_at = CURRENT_TIMESTAMP,
                    closed_at = NULL,
                    close_reason = '',
                    comment = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (new_key_comment.strip(), previous_assignment["id"]),
            )
            assignment_id = int(previous_assignment["id"])
        else:
            cursor = conn.execute(
                """
                INSERT INTO employee_keys(
                    employee_id,
                    key_id,
                    status,
                    issued_at,
                    closed_at,
                    close_reason,
                    comment,
                    created_at,
                    updated_at
                )
                VALUES(
                    ?,
                    ?,
                    'active',
                    CURRENT_TIMESTAMP,
                    NULL,
                    '',
                    ?,
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                )
                """,
                (employee_id, key_id, new_key_comment.strip()),
            )
            assignment_id = int(cursor.lastrowid)

        conn.execute(
            """
            UPDATE keys
            SET is_used = 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (key_id,),
        )

        set_key_assignment_on_connection(
            conn,
            key_id,
            "employee",
            employee_id=employee_id,
            assigned_by="Учёт сотрудников",
            note=new_key_comment,
        )

        return assignment_id


def attach_key_to_employee(employee_id: int, key_id: int) -> None:
    issue_key_to_employee(
        employee_id=employee_id,
        key_id=key_id,
    )


def close_employee_key(
    employee_id: int,
    assignment_id: int,
    status: str,
    close_reason: str,
    comment: str = "",
) -> None:
    if status not in CLOSED_KEY_STATUSES:
        raise ValueError("Недопустимый статус ключа.")

    if not close_reason.strip():
        raise ValueError("Не указана причина закрытия ключа.")

    with db() as conn:
        assignment = conn.execute(
            """
            SELECT id, key_id
            FROM employee_keys
            WHERE id = ?
              AND employee_id = ?
              AND status = 'active'
            """,
            (assignment_id, employee_id),
        ).fetchone()

        if not assignment:
            raise ValueError("Действующий ключ сотрудника не найден.")

        conn.execute(
            """
            UPDATE employee_keys
            SET
                status = ?,
                closed_at = CURRENT_TIMESTAMP,
                close_reason = ?,
                comment = CASE
                    WHEN ? <> '' THEN ?
                    ELSE comment
                END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                status,
                close_reason.strip(),
                comment.strip(),
                comment.strip(),
                assignment_id,
            ),
        )

        conn.execute(
            """
            UPDATE keys
            SET is_used = 0,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (assignment["key_id"],),
        )
        release_key_on_connection(
            conn,
            int(assignment["key_id"]),
            close_reason,
        )
        if status in {"lost", "damaged"}:
            conn.execute(
                """
                UPDATE keys
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    "lost" if status == "lost" else "defective",
                    assignment["key_id"],
                ),
            )


def update_employee_key_comment(
    employee_id: int,
    assignment_id: int,
    comment: str,
) -> None:
    with db() as conn:
        cursor = conn.execute(
            """
            UPDATE employee_keys
            SET
                comment = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND employee_id = ?
            """,
            (comment.strip(), assignment_id, employee_id),
        )

        if cursor.rowcount == 0:
            raise ValueError("Запись о выдаче ключа не найдена.")


def update_employee_key_history(
    employee_id: int,
    assignment_id: int,
    status: str,
    close_reason: str,
    comment: str,
) -> None:
    if status not in CLOSED_KEY_STATUSES:
        raise ValueError("Недопустимый статус ключа.")

    if not close_reason.strip():
        raise ValueError("Не указана причина закрытия ключа.")

    with db() as conn:
        cursor = conn.execute(
            """
            UPDATE employee_keys
            SET
                status = ?,
                close_reason = ?,
                comment = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND employee_id = ?
              AND status <> 'active'
            """,
            (
                status,
                close_reason.strip(),
                comment.strip(),
                assignment_id,
                employee_id,
            ),
        )

        if cursor.rowcount == 0:
            raise ValueError("Старый ключ не найден в истории.")


def dismiss_employee(
    employee_id: int,
    comment: str = "",
) -> None:
    with db() as conn:
        employee = conn.execute(
            """
            SELECT id
            FROM employees
            WHERE id = ? AND enabled = 1
            """,
            (employee_id,),
        ).fetchone()

        if not employee:
            raise ValueError("Сотрудник не найден или уже уволен.")

        active_keys = conn.execute(
            """
            SELECT id, key_id
            FROM employee_keys
            WHERE employee_id = ?
              AND status = 'active'
            """,
            (employee_id,),
        ).fetchall()

        if active_keys:
            active_key_ids = [
                int(active_key["key_id"])
                for active_key in active_keys
            ]
            key_placeholders = ",".join("?" for _ in active_key_ids)
            conn.execute(
                """
                UPDATE employee_keys
                SET
                    status = 'dismissed',
                    closed_at = CURRENT_TIMESTAMP,
                    close_reason = 'Сотрудник уволен',
                    comment = CASE
                        WHEN ? <> '' THEN ?
                        ELSE comment
                    END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE employee_id = ?
                  AND status = 'active'
                """,
                (comment.strip(), comment.strip(), employee_id),
            )

            conn.execute(
                f"""
                UPDATE keys
                SET is_used = 0,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id IN ({key_placeholders})
                """,
                active_key_ids,
            )
            for active_key in active_keys:
                release_key_on_connection(
                    conn,
                    int(active_key["key_id"]),
                    "Сотрудник уволен",
                )

        conn.execute(
            """
            UPDATE employees
            SET
                enabled = 0,
                dismissed_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP,
                note = CASE
                    WHEN ? <> '' THEN ?
                    ELSE note
                END
            WHERE id = ?
            """,
            (comment.strip(), comment.strip(), employee_id),
        )


def soft_delete_employee(employee_id: int) -> None:
    dismiss_employee(
        employee_id=employee_id,
        comment="Сотрудник уволен",
    )


def remove_employee_key(employee_id: int, key_id: int) -> None:
    with db() as conn:
        assignment = conn.execute(
            """
            SELECT id
            FROM employee_keys
            WHERE employee_id = ?
              AND key_id = ?
              AND status = 'active'
            LIMIT 1
            """,
            (employee_id, key_id),
        ).fetchone()

    if not assignment:
        raise ValueError("Действующий ключ сотрудника не найден.")

    close_employee_key(
        employee_id=employee_id,
        assignment_id=assignment["id"],
        status="inactive",
        close_reason="Ключ деактивирован вручную",
    )
