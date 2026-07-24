"""Transactional PostgreSQL CRUD smoke test.

All inserted rows are rolled back, so the target database is left unchanged.
"""

from __future__ import annotations

import argparse
from uuid import uuid4

from sqlalchemy import create_engine, delete, insert, select, update
from sqlalchemy.orm import Session

from app.models import employees, key_types, keys, users
from app.settings import settings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=settings.database_url)
    args = parser.parse_args()
    if not args.database_url.startswith("postgresql+psycopg://"):
        raise SystemExit("Smoke-тест предназначен только для PostgreSQL + psycopg.")

    suffix = uuid4().hex[:12]
    engine = create_engine(args.database_url, pool_pre_ping=True)
    connection = engine.connect()
    transaction = connection.begin()
    try:
        with Session(
            bind=connection,
            autoflush=False,
            join_transaction_mode="create_savepoint",
        ) as session:
            employee_id = session.execute(
                insert(employees)
                .values(
                    full_name=f"Smoke Employee {suffix}",
                    note="temporary CRUD smoke test",
                    created_by="smoke-test",
                )
                .returning(employees.c.id)
            ).scalar_one()
            user_id = session.execute(
                insert(users)
                .values(
                    full_name=f"Smoke User {suffix}",
                    login=f"smoke_{suffix}",
                    password_hash="not-a-real-password",
                    role="observer",
                )
                .returning(users.c.id)
            ).scalar_one()
            key_type_id = session.execute(
                insert(key_types)
                .values(name=f"Smoke Type {suffix}", color="#2A9DF4")
                .returning(key_types.c.id)
            ).scalar_one()
            key_id = session.execute(
                insert(keys)
                .values(
                    key_type_id=key_type_id,
                    number=f"SMOKE-{suffix}",
                    hex_value=f"ABCD{suffix.upper()}",
                    key_type=f"Smoke Type {suffix}",
                    created_by="smoke-test",
                )
                .returning(keys.c.id)
            ).scalar_one()

            session.execute(
                update(employees)
                .where(employees.c.id == employee_id)
                .values(note="updated")
            )
            employee_note = session.scalar(
                select(employees.c.note).where(employees.c.id == employee_id)
            )
            if employee_note != "updated":
                raise RuntimeError("UPDATE/SELECT employees не прошёл")

            session.execute(delete(keys).where(keys.c.id == key_id))
            session.execute(
                delete(key_types).where(key_types.c.id == key_type_id)
            )
            session.execute(delete(users).where(users.c.id == user_id))
            session.execute(
                delete(employees).where(employees.c.id == employee_id)
            )
            session.flush()
            if session.scalar(
                select(employees.c.id).where(employees.c.id == employee_id)
            ) is not None:
                raise RuntimeError("DELETE employees не прошёл")

        print(
            "PostgreSQL CRUD smoke-тест успешен: "
            "INSERT, SELECT, UPDATE и DELETE выполнены."
        )
    finally:
        transaction.rollback()
        connection.close()
        engine.dispose()
        print("Тестовая транзакция отменена; данные не сохранены.")


if __name__ == "__main__":
    main()
