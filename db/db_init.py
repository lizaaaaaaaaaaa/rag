import sqlite3

conn = sqlite3.connect("db/users.db")
c = conn.cursor()
c.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE,
    name TEXT,
    picture TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
""")
conn.commit()
conn.close()
