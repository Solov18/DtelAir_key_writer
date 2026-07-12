from app.db import db


ACTIVE_KEY_STATUS = "active"

CLOSED_KEY_STATUSES = {
    "replaced",
    "lost",
    "damaged",
    "dismissed",
    "inactive",
}


def get_active_employees() -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT
                e.*,

                active_ek.id AS active_assignment_id,
                active_ek.key_id AS active_key_id,
                active_ek.issued_at AS active_key_issued_at,
                active_ek.comment AS active_key_comment,

                active_key.number AS active_key_number,
                active_key.hex_value AS active_key_hex_value,
                active_key.key_type AS active_key_type,

                (
                    SELECT COUNT(*)
                    FROM employee_keys history_ek
                    WHERE history_ek.employee_id = e.id
                      AND history_ek.status <> 'active'
                ) AS history_count

            FROM employees e

            LEFT JOIN employee_keys active_ek
                ON active_ek.employee_id = e.id
               AND active_ek.status = 'active'

            LEFT JOIN keys active_key
                ON active_key.id = active_ek.key_id

            WHERE e.enabled = 1
            ORDER BY e.full_name COLLATE NOCASE
            """
        ).fetchall()

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


def create_employee(full_name: str, note: str = "") -> int:
    normalized_name = full_name.strip()

    if not normalized_name:
        raise ValueError("Не указано ФИО сотрудника.")

    with db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO employees(
                full_name,
                note,
                enabled,
                created_at,
                updated_at
            )
            VALUES (?, ?, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (normalized_name, note.strip()),
        )

        return int(cursor.lastrowid)


def update_employee(
    employee_id: int,
    full_name: str,
    note: str = "",
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
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND enabled = 1
            """,
            (normalized_name, note.strip(), employee_id),
        )

        if cursor.rowcount == 0:
            raise ValueError("Сотрудник не найден.")


def get_employee_active_key(employee_id: int) -> dict | None:
    with db() as conn:
        row = conn.execute(
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
              AND ek.status = 'active'
            LIMIT 1
            """,
            (employee_id,),
        ).fetchone()

        return dict(row) if row else None


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
            "SELECT id FROM keys WHERE id = ?",
            (key_id,),
        ).fetchone()

        if not key:
            raise ValueError("Ключ не найден.")

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

        current_key = conn.execute(
            """
            SELECT id, key_id
            FROM employee_keys
            WHERE employee_id = ?
              AND status = 'active'
            LIMIT 1
            """,
            (employee_id,),
        ).fetchone()

        if current_key and current_key["key_id"] == key_id:
            conn.execute(
                """
                UPDATE employee_keys
                SET
                    comment = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (new_key_comment.strip(), current_key["id"]),
            )
            return int(current_key["id"])

        if current_key:
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
                    old_key_status,
                    old_key_reason.strip() or "Выдан новый ключ",
                    old_key_comment.strip(),
                    old_key_comment.strip(),
                    current_key["id"],
                ),
            )

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

        if current_key:
            conn.execute(
                """
                UPDATE keys
                SET is_used = 0,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                  AND NOT EXISTS (
                      SELECT 1
                      FROM employee_keys
                      WHERE key_id = ?
                        AND status = 'active'
                  )
                """,
                (current_key["key_id"], current_key["key_id"]),
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

        active_key = conn.execute(
            """
            SELECT id, key_id
            FROM employee_keys
            WHERE employee_id = ?
              AND status = 'active'
            LIMIT 1
            """,
            (employee_id,),
        ).fetchone()

        if active_key:
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
                WHERE id = ?
                """,
                (comment.strip(), comment.strip(), active_key["id"]),
            )

            conn.execute(
                """
                UPDATE keys
                SET is_used = 0,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (active_key["key_id"],),
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
