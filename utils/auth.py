# utils/auth.py
import os
import sqlite3
import bcrypt
from typing import List, Tuple, Optional
from unicodedata import normalize

# ===== 設定 =====
DB_PATH = os.getenv("USERS_DB_PATH", "users.db")

# ===== 正規化ユーティリティ =====
def _norm_username(u: str) -> str:
    return (u or "").strip().lower()

def _norm_password(p: str) -> str:
    return normalize("NFC", p or "")

def _is_bcrypt_string(s: str) -> bool:
    return s.startswith("$2a$") or s.startswith("$2b$") or s.startswith("$2y$")

def get_db_path() -> str:
    return DB_PATH

# ===== 初期化 =====
def create_users_table() -> None:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,   -- bcrypt文字列をTEXTで保存
            role TEXT NOT NULL DEFAULT 'user'
        )
    """)
    con.commit()
    con.close()

# ===== CRUD（必ずここを通す）=====
def signup_user(username: str, password: str, role: str = "user") -> Tuple[bool, str]:
    un = _norm_username(username)
    pw = _norm_password(password)
    if not un or not pw:
        return False, "ユーザー名とパスワードは必須です"

    create_users_table()
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT 1 FROM users WHERE username=?", (un,))
    if cur.fetchone():
        con.close()
        return False, "既に存在するユーザーです"

    hashed = bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    cur.execute("INSERT INTO users (username, password, role) VALUES (?,?,?)", (un, hashed, role))
    con.commit(); con.close()
    return True, "ユーザーを作成しました"

def update_password(username: str, new_password: str) -> Tuple[bool, str]:
    un = _norm_username(username)
    pw = _norm_password(new_password)
    if not pw:
        return False, "新しいパスワードを入力してください"

    create_users_table()
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("SELECT 1 FROM users WHERE username=?", (un,))
    if not cur.fetchone():
        con.close()
        return False, "ユーザーが見つかりません"

    hashed = bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    cur.execute("UPDATE users SET password=? WHERE username=?", (hashed, un))
    con.commit(); con.close()
    return True, "パスワードを更新しました"

def update_role(username: str, role: str) -> Tuple[bool, str]:
    un = _norm_username(username)
    create_users_table()
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("SELECT 1 FROM users WHERE username=?", (un,))
    if not cur.fetchone():
        con.close()
        return False, "ユーザーが見つかりません"
    cur.execute("UPDATE users SET role=? WHERE username=?", (role, un))
    con.commit(); con.close()
    return True, "権限を更新しました"

def delete_user(username: str) -> Tuple[bool, str]:
    un = _norm_username(username)
    create_users_table()
    if un == "admin":
        return False, "admin は削除できません"
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("DELETE FROM users WHERE username=?", (un,))
    con.commit(); con.close()
    return True, "ユーザーを削除しました"

def get_users() -> List[Tuple[int, str, str]]:
    create_users_table()
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("SELECT id, username, role FROM users ORDER BY id ASC")
    rows = cur.fetchall()
    con.close()
    return rows

def get_user_role(username: str) -> str:
    un = _norm_username(username)
    create_users_table()
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("SELECT role FROM users WHERE username=?", (un,))
    row = cur.fetchone(); con.close()
    return row[0] if row and row[0] else "user"

# ===== 認証（平文→自動移行対応）=====
def login_user(username: str, password: str) -> bool:
    un = _norm_username(username)
    pw = _norm_password(password)

    create_users_table()
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("SELECT password FROM users WHERE username=?", (un,))
    row = cur.fetchone(); con.close()
    if not row:
        return False

    stored = row[0] if isinstance(row[0], str) else str(row[0])

    # 旧DBの平文救済：一致したら即 bcrypt へ移行
    if not _is_bcrypt_string(stored):
        if stored == pw:
            update_password(un, pw)
            return True
        return False

    return bcrypt.checkpw(pw.encode("utf-8"), stored.encode("utf-8"))

# ===== 起動時 admin 自動作成（環境変数がある時だけ）=====
def ensure_admin_bootstrap() -> bool:
    create_users_table()
    admin_user = _norm_username(os.getenv("ADMIN_USERNAME", "admin"))
    admin_pass = os.getenv("ADMIN_PASSWORD")
    if not admin_pass:
        return False

    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("SELECT 1 FROM users WHERE username=?", (admin_user,))
    if cur.fetchone():
        con.close(); return False

    pw = _norm_password(admin_pass)
    hashed = bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    cur.execute("INSERT INTO users (username, password, role) VALUES (?,?,?)",
                (admin_user, hashed, "admin"))
    con.commit(); con.close()
    return True
