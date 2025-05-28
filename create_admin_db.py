import sqlite3
import bcrypt

conn = sqlite3.connect("users.db")
c = conn.cursor()

# テーブル作成
c.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE,
    password TEXT,
    role TEXT
)
""")

# パスワードをハッシュ化
password = b"adminpass"
hashed = bcrypt.hashpw(password, bcrypt.gensalt())

# 管理者ユーザー登録
c.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", ("admin", hashed, "admin"))
conn.commit()
conn.close()

print("adminユーザー作成完了！")
