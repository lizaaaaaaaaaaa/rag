# utils/auth.py
import os
import sqlite3
import base64
import hashlib
import hmac
from typing import List, Dict, Tuple

# --- Config ---
def get_db_path() -> str:
    """Users DB のパス。Cloud Run では /tmp を推奨"""
    return os.getenv("USERS_DB_PATH", "users.db")

DB_PATH = get_db_path()
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD_ENV = os.getenv("ADMIN_PASSWORD")  # 任意。セット時のみブートストラップ

# --- Low-level helpers ---
def _connect() -> sqlite3.Connection:
    path = get_db_path()
    dir_ = os.path.dirname(path)
    if dir_ and not os.path.exists(dir_):
        os.makedirs(dir_, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    with conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
    return conn

def _hash_password(password: str, *, salt: bytes=None, iterations: int = 200_000) -> str:
    if salt is None:
        salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"

def _verify_password(password: str, stored: str) -> bool:
    if not stored:
        return False
    try:
        if stored.startswith("pbkdf2_sha256$"):
            _, it_s, salt_b64, hash_b64 = stored.split("$")
            iterations = int(it_s)
            salt = base64.b64decode(salt_b64)
            dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
            return hmac.compare_digest(base64.b64encode(dk).decode(), hash_b64)
        # 互換: もし旧DBがプレーンならそのまま比較
        return password == stored
    except Exception:
        return False

# --- Schema ---
def create_users_table() -> None:
    conn = _connect()
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                username  TEXT PRIMARY KEY,
                password  TEXT NOT NULL,
                role      TEXT NOT NULL CHECK(role IN ('user','admin')),
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_users_updated
            AFTER UPDATE ON users
            FOR EACH ROW BEGIN
                UPDATE users SET updated_at = CURRENT_TIMESTAMP WHERE username = OLD.username;
            END;
        """)

# --- CRUD & Auth ---
def signup_user(username: str, password: str, role: str = "user") -> bool:
    if not username or not password:
        return False
    create_users_table()
    conn = _connect()
    try:
        with conn:
            conn.execute(
                "INSERT INTO users(username, password, role) VALUES(?,?,?)",
                (username.strip().lower(), _hash_password(password), role)
            )
        return True
    except sqlite3.IntegrityError:
        return False

def update_password(username: str, new_password: str) -> Tuple[bool, str]:
    if not username or not new_password:
        return False, "username / password required"
    conn = _connect()
    with conn:
        cur = conn.execute("UPDATE users SET password=? WHERE username=?",
                           (_hash_password(new_password), username.strip().lower()))
        if cur.rowcount == 0:
            return False, "user not found"
    return True, "password updated"

def update_role(username: str, new_role: str) -> Tuple[bool, str]:
    if new_role not in ("user", "admin"):
        return False, "invalid role"
    conn = _connect()
    with conn:
        cur = conn.execute("UPDATE users SET role=? WHERE username=?",
                           (new_role, username.strip().lower()))
        if cur.rowcount == 0:
            return False, "user not found"
    return True, "role updated"

def delete_user(username: str) -> Tuple[bool, str]:
    if username == ADMIN_USERNAME:
        return False, "cannot delete bootstrap admin"
    conn = _connect()
    with conn:
        cur = conn.execute("DELETE FROM users WHERE username=?", (username.strip().lower(),))
        if cur.rowcount == 0:
            return False, "user not found"
    return True, "user deleted"

def get_users() -> List[Dict]:
    conn = _connect()
    cur = conn.execute("SELECT username, role, created_at, updated_at FROM users ORDER BY username")
    return [dict(r) for r in cur.fetchall()]

def user_exists(username: str) -> bool:
    conn = _connect()
    cur = conn.execute("SELECT 1 FROM users WHERE username=?", (username.strip().lower(),))
    return cur.fetchone() is not None

def get_user_role(username: str) -> str:
    conn = _connect()
    cur = conn.execute("SELECT role FROM users WHERE username=?", (username.strip().lower(),))
    row = cur.fetchone()
    return (row["role"] if row else "user")

def login_user(username: str, password: str) -> bool:
    if not username or not password:
        return False
    conn = _connect()
    cur = conn.execute("SELECT password FROM users WHERE username=?", (username.strip().lower(),))
    row = cur.fetchone()
    if not row:
        return False
    return _verify_password(password, row["password"])

# --- Bootstrap ---
def ensure_admin_bootstrap() -> bool:
    """ADMIN_PASSWORD がセットされ、admin が未作成なら作成。作成時 True"""
    create_users_table()
    if user_exists(ADMIN_USERNAME):
        return False
    if not ADMIN_PASSWORD_ENV:
        return False
    conn = _connect()
    with conn:
        conn.execute(
            "INSERT INTO users(username, password, role) VALUES(?,?,?)",
            (ADMIN_USERNAME, _hash_password(ADMIN_PASSWORD_ENV), "admin")
        )
    return True
