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

    count = db.execute(
        f'SELECT COUNT(*) FROM "{table_name}"'
    ).fetchone()[0]

    print(f"{table_name}: {count}")

db.close()