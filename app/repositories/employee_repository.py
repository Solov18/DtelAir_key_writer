from app.db import db


def get_active_employees() -> list[dict]:
    with db() as conn:
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT
                    e.*,
                    COUNT(ek.key_id) AS keys_count,
                    GROUP_CONCAT(k.number, ', ') AS key_numbers
                FROM employees e
                LEFT JOIN employee_keys ek ON ek.employee_id = e.id
                LEFT JOIN keys k ON k.id = ek.key_id
                WHERE e.enabled = 1
                GROUP BY e.id
                ORDER BY e.full_name
                """
            )
        ]


def get_employee(employee_id: int) -> dict | None:
    with db() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM employees
            WHERE id = ? AND enabled = 1
            """,
            (employee_id,),
        ).fetchone()

        return dict(row) if row else None


def get_employee_by_name(full_name: str) -> dict | None:
    with db() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM employees
            WHERE enabled = 1 AND full_name = ?
            LIMIT 1
            """,
            (full_name.strip(),),
        ).fetchone()

        return dict(row) if row else None


def get_employees_count() -> int:
    with db() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM employees WHERE enabled = 1"
        ).fetchone()[0]


def get_employee_keys_count() -> int:
    with db() as conn:
        return conn.execute(
            """
            SELECT COUNT(*)
            FROM employee_keys ek
            JOIN employees e ON e.id = ek.employee_id
            WHERE e.enabled = 1
            """
        ).fetchone()[0]


def create_employee(full_name: str, note: str = "") -> None:
    with db() as conn:
        conn.execute(
            """
            INSERT INTO employees(full_name, note)
            VALUES(?, ?)
            """,
            (full_name.strip(), note.strip()),
        )


def soft_delete_employee(employee_id: int) -> None:
    with db() as conn:
        conn.execute(
            """
            UPDATE employees
            SET enabled = 0
            WHERE id = ?
            """,
            (employee_id,),
        )


def attach_key_to_employee(employee_id: int, key_id: int) -> None:
    with db() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO employee_keys(employee_id, key_id)
            VALUES(?, ?)
            """,
            (employee_id, key_id),
        )


def get_employee_keys(employee_id: int) -> list[dict]:
    with db() as conn:
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT k.*
                FROM keys k
                JOIN employee_keys ek ON ek.key_id = k.id
                WHERE ek.employee_id = ?
                ORDER BY k.number
                """,
                (employee_id,),
            )
        ]


def remove_employee_key(employee_id: int, key_id: int) -> None:
    with db() as conn:
        conn.execute(
            """
            DELETE FROM employee_keys
            WHERE employee_id = ? AND key_id = ?
            """,
            (employee_id, key_id),
        )