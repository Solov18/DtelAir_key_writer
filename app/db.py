import sqlite3
from pathlib import Path
from contextlib import contextmanager

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / 'data'
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / 'app.db'

@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db():
    with db() as conn:
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            number TEXT UNIQUE NOT NULL,
            hex_value TEXT NOT NULL,
            key_type TEXT DEFAULT '',
            note TEXT DEFAULT '',
            is_used INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            note TEXT DEFAULT '',
            enabled INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS panels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            address TEXT NOT NULL,
            entrance TEXT DEFAULT '',
            name TEXT NOT NULL,
            mac TEXT UNIQUE NOT NULL,
            tags TEXT DEFAULT '',
            enabled INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS uk_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            note TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS uk_group_panels (
            group_id INTEGER NOT NULL,
            panel_id INTEGER NOT NULL,
            UNIQUE(group_id, panel_id)
        );
        CREATE TABLE IF NOT EXISTS operation_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mode TEXT NOT NULL,
            printed_number TEXT DEFAULT '',
            hex_value TEXT NOT NULL,
            flat_num TEXT DEFAULT '',
            mac TEXT NOT NULL,
            panel_name TEXT DEFAULT '',
            status TEXT NOT NULL,
            response TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        ''')
        columns = [
            row["name"]
            for row in conn.execute("PRAGMA table_info(operation_log)").fetchall()
        ]

        if "address" not in columns:
            conn.execute("ALTER TABLE operation_log ADD COLUMN address TEXT DEFAULT ''")

        if "apartment" not in columns:
            conn.execute("ALTER TABLE operation_log ADD COLUMN apartment TEXT DEFAULT ''")
        # demo data, only if empty
        count = conn.execute('SELECT COUNT(*) FROM panels').fetchone()[0]
        if count == 0:
            rows = [
                ('Тепличная 65', 'общий вход', 'Тепличная 65 общий вход', '08:13:CD:00:1D:C2', 'employee,uk,gate'),
                ('Тепличная 65', 'калитка', 'Тепличная 65 калитка', 'D4:A0:FB:1B:36:90', 'employee,uk,gate'),
                ('Ясногорская 16/2 к.14', 'подъезд', 'Ясногорская 16/2 к.14 подъезд', '08:53:CD:19:62:6E', 'employee,uk'),
            ]
            conn.executemany('INSERT OR IGNORE INTO panels(address,entrance,name,mac,tags) VALUES(?,?,?,?,?)', rows)
        kcount = conn.execute('SELECT COUNT(*) FROM keys').fetchone()[0]
        if kcount == 0:
            conn.executemany('INSERT OR IGNORE INTO keys(number,hex_value,key_type) VALUES(?,?,?)', [
                ('5654','363FFAD7','простой'), ('39107','363FFAD7','простой'), ('39300','3643A6F1','простой'), ('001101','362E0847','бесплатный')
            ])
