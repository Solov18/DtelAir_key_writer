from app.db import db


def get_recent_keys(limit: int = 300) -> list[dict]:
    with db() as conn:
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT *
                FROM keys
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            )
        ]