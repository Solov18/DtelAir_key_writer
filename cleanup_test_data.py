import sqlite3
from pathlib import Path


DB_PATH = Path("data/app.db")


def main() -> None:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"База не найдена: {DB_PATH.resolve()}")

    connection = sqlite3.connect(DB_PATH)

    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN")

        tables_to_clear = [
            "employee_keys",
            "key_assignments",
            "keys",
            "key_types",
            "operation_log",
            "panels",
            "uk_group_keys",
            "uk_group_panels",
            "uk_integrations",
            "uk_notification_drafts",
            "uk_groups",
        ]

        for table_name in tables_to_clear:
            connection.execute(f'DELETE FROM "{table_name}"')
            print(f"Очищено: {table_name}")

        placeholders = ", ".join("?" for _ in tables_to_clear)

        connection.execute(
            f"""
            DELETE FROM sqlite_sequence
            WHERE name IN ({placeholders})
            """,
            tables_to_clear,
        )

        connection.commit()

        print()
        print("Очистка завершена успешно.")
        print("Таблицы employees и users сохранены.")

    except Exception:
        connection.rollback()
        print("Произошла ошибка. Все изменения отменены.")
        raise

    finally:
        connection.close()


if __name__ == "__main__":
    main()