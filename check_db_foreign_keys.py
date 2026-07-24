import sqlite3


db = sqlite3.connect("data/app.db")

tables = db.execute(
    """
    SELECT name
    FROM sqlite_master
    WHERE type = 'table'
      AND name NOT LIKE 'sqlite_%'
    ORDER BY name
    """
).fetchall()

for row in tables:
    table_name = row[0]
    foreign_keys = db.execute(
        f'PRAGMA foreign_key_list("{table_name}")'
    ).fetchall()

    print(f"\n{table_name}")

    if not foreign_keys:
        print("  внешних ключей нет")
        continue

    for foreign_key in foreign_keys:
        print(f"  {foreign_key}")

db.close()