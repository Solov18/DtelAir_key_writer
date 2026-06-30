from app.db import db


def get_last_operations(limit: int = 500) -> list[dict]:
    with db() as conn:
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT *
                FROM operation_log
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            )
        ]