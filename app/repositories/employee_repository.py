from app.db import db


def get_active_employees() -> list[dict]:
    with db() as conn:
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT *
                FROM employees
                WHERE enabled = 1
                ORDER BY full_name
                """
            )
        ]


def create_employee(
    full_name: str,
    note: str = "",
) -> None:
    with db() as conn:
        conn.execute(
            """
            INSERT INTO employees(full_name, note)
            VALUES(?, ?)
            """,
            (
                full_name.strip(),
                note.strip(),
            ),
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