# utils/auth.py
import os, sqlite3, base64, hashlib, hmac
from typing import List, Dict, Tuple

# ---- Config ----
def get_db_path() -> str:
    # Cloud Run は /tmp が書き込み可
    return os.getenv("USERS_DB_PATH", "users.db")

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD_ENV = os.getenv("ADMIN_PASSWORD")  # あれば起動時にadmin作成

# ---- DB helpers ----
def _connect() -> sqlite3.Connection:
    path = get_db_path()
    dir_ = os.path.dirname(path)
    if dir_ and not os.path.exists(dir_):
        os.makedirs(dir_, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn

def _hash_password(password: str, *, salt: bytes = None, iterations: int = 200_000) -> str:
    import os
    if salt is None:
        salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"

def _verify_password(password: str, stored: str) -> bool:
    try:
        if stored.startswith("pbkdf2_sha256$"):
            _, it_s, salt_b64, hash_b64 = stored.split("$")
            dk = hashlib.pbkdf2_hmac("sha256", password.encode(),
                                     base64.b64decode(salt_b64), int(it_s))
            return hmac.compare_digest(base64.b64encode(dk).decode(), hash_b64)
        # 旧DBが平文の場合への後方互換
        return password == stored
    except Exception:
        return False

# ---- Schema (with migrations) ----
def _colset(conn: sqlite3.Connection) -> set:
    cur = conn.execute("PRAGMA table_info(users)")
    return {r["name"] for r in cur.fetchall()}

def create_users_table() -> None:
    """
    users テーブルを作成（なければ）し、足りない列を自動追加。
    旧DBでも role/created_at/updated_at を追加し、更新トリガを再作成。
    """
    conn = _connect()
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users(
                username  TEXT PRIMARY KEY,
                password  TEXT NOT NULL
            )
        """)
        cols = _colset(conn)
        if "role" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'")
        if "created_at" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN created_at TEXT DEFAULT CURRENT_TIMESTAMP")
        if "updated_at" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN updated_at TEXT DEFAULT CURRENT_TIMESTAMP")

        conn.execute("DROP TRIGGER IF EXISTS trg_users_updated")
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_users_updated
            AFTER UPDATE ON users
            FOR EACH ROW
            BEGIN
                UPDATE users SET updated_at = CURRENT_TIMESTAMP WHERE username = OLD.username;
            END;
        """)

# ---- CRUD & Auth ----
def signup_user(username: str, password: str, role: str = "user") -> Tuple[bool, str]:
    create_users_table()
    u = (username or "").strip().lower()
    if not u or not password:
        return False, "username / password required"
    conn = _connect()
    try:
        with conn:
            conn.execute("INSERT INTO users(username, password, role) VALUES(?,?,?)",
                         (u, _hash_password(password), role))
        return True, "created"
    except sqlite3.IntegrityError:
        return False, "duplicate"

def update_password(username: str, new_password: str) -> Tuple[bool, str]:
    create_users_table()
    u = (username or "").strip().lower()
    if not u or not new_password:
        return False, "username / password required"
    conn = _connect()
    with conn:
        cur = conn.execute("UPDATE users SET password=? WHERE username=?",
                           (_hash_password(new_password), u))
        if cur.rowcount == 0:
            return False, "user not found"
    return True, "password updated"

def update_role(username: str, new_role: str) -> Tuple[bool, str]:
    create_users_table()
    if new_role not in ("user", "admin"):
        return False, "invalid role"
    conn = _connect()
    with conn:
        cur = conn.execute("UPDATE users SET role=? WHERE username=?",
                           (new_role, (username or "").strip().lower()))
        if cur.rowcount == 0:
            return False, "user not found"
    return True, "role updated"

def delete_user(username: str) -> Tuple[bool, str]:
    if (username or "").strip().lower() == ADMIN_USERNAME:
        return False, "cannot delete bootstrap admin"
    conn = _connect()
    with conn:
        cur = conn.execute("DELETE FROM users WHERE username=?",
                           ((username or "").strip().lower(),))
        if cur.rowcount == 0:
            return False, "user not found"
    return True, "deleted"

def get_users() -> List[Dict]:
    conn = _connect()
    cur = conn.execute("SELECT username, role, created_at, updated_at FROM users ORDER BY username")
    return [dict(r) for r in cur.fetchall()]

def user_exists(username: str) -> bool:
    conn = _connect()
    cur = conn.execute("SELECT 1 FROM users WHERE username=?", ((username or "").strip().lower(),))
    return cur.fetchone() is not None

def get_user_role(username: str) -> str:
    conn = _connect()
    cur = conn.execute("SELECT role FROM users WHERE username=?", ((username or "").strip().lower(),))
    row = cur.fetchone()
    return row["role"] if row else "user"

def login_user(username: str, password: str) -> bool:
    if not username or not password:
        return False
    conn = _connect()
    cur = conn.execute("SELECT password FROM users WHERE username=?", ((username or "").strip().lower(),))
    row = cur.fetchone()
    return _verify_password(password, row["password"]) if row else False

def ensure_admin_bootstrap() -> bool:
    """ADMIN_PASSWORD が設定され、admin 不在なら作成（作成時 True）"""
    create_users_table()
    if user_exists(ADMIN_USERNAME):
        return False
    if not ADMIN_PASSWORD_ENV:
        return False
    conn = _connect()
    with conn:
        conn.execute("INSERT INTO users(username, password, role) VALUES(?,?,?)",
                     (ADMIN_USERNAME, _hash_password(ADMIN_PASSWORD_ENV), "admin"))
    return True
