# utils/auth.py
import os
import sqlite3
import bcrypt
from typing import List, Tuple, Optional

# ====== 設定 ======
DB_PATH = os.getenv("USERS_DB_PATH", "users.db")


# ====== 初期化 ======
def create_users_table() -> None:
    """usersテーブルを作成（なければ）"""
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,      -- bcryptの文字列をTEXTで保存
            role TEXT NOT NULL DEFAULT 'user'
        )
        """
    )
    con.commit()
    con.close()


# ====== 内部ユーティリティ ======
def _is_bcrypt_string(s: str) -> bool:
    return s.startswith("$2a$") or s.startswith("$2b$") or s.startswith("$2y$")


# ====== 認証・ユーザー管理（ここだけを使う） ======
def signup_user(username: str, password: str, role: str = "user") -> Tuple[bool, str]:
    """新規作成：必ずbcryptでハッシュして保存"""
    if not username or not password:
        return False, "ユーザー名とパスワードは必須です"

    create_users_table()
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    cur.execute("SELECT 1 FROM users WHERE username=?", (username,))
    if cur.fetchone():
        con.close()
        return False, "既に存在するユーザーです"

    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    cur.execute(
        "INSERT INTO users (username, password, role) VALUES (?,?,?)",
        (username, hashed, role),
    )
    con.commit()
    con.close()
    return True, "ユーザーを作成しました"


def login_user(username: str, password: str) -> bool:
    """
    ログイン：bcryptで照合。
    もし古いDBに“平文”が残っていて、入力が一致した場合はその場でbcryptへ自動移行。
    """
    create_users_table()
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT password FROM users WHERE username=?", (username,))
    row = cur.fetchone()
    con.close()

    if not row:
        return False

    stored = row[0] if isinstance(row[0], str) else str(row[0])

    # 平文が残っている場合の救済（正しい入力時のみハッシュ化して即時更新）
    if not _is_bcrypt_string(stored):
        if stored == password:
            update_password(username, password)  # bcrypt化して保存
            return True
        return False

    return bcrypt.checkpw(password.encode("utf-8"), stored.encode("utf-8"))


def update_password(username: str, new_password: str) -> Tuple[bool, str]:
    """パスワード更新：必ずbcryptでハッシュ"""
    if not new_password:
        return False, "新しいパスワードを入力してください"

    create_users_table()
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    cur.execute("SELECT 1 FROM users WHERE username=?", (username,))
    if not cur.fetchone():
        con.close()
        return False, "ユーザーが見つかりません"

    hashed = bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    cur.execute("UPDATE users SET password=? WHERE username=?", (hashed, username))
    con.commit()
    con.close()
    return True, "パスワードを更新しました"


def update_role(username: str, role: str) -> Tuple[bool, str]:
    """権限変更"""
    create_users_table()
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    cur.execute("SELECT 1 FROM users WHERE username=?", (username,))
    if not cur.fetchone():
        con.close()
        return False, "ユーザーが見つかりません"

    cur.execute("UPDATE users SET role=? WHERE username=?", (role, username))
    con.commit()
    con.close()
    return True, "権限を更新しました"


def delete_user(username: str) -> Tuple[bool, str]:
    """ユーザー削除（adminの誤削除は防止）"""
    create_users_table()
    if username == "admin":
        return False, "admin は削除できません"

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("DELETE FROM users WHERE username=?", (username,))
    con.commit()
    con.close()
    return True, "ユーザーを削除しました"


def get_users() -> List[Tuple[int, str, str]]:
    """(id, username, role) の一覧"""
    create_users_table()
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT id, username, role FROM users ORDER BY id ASC")
    rows = cur.fetchall()
    con.close()
    return rows


def get_user_role(username: str) -> str:
    """ロール取得（UI側の制御用）"""
    create_users_table()
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT role FROM users WHERE username=?", (username,))
    row = cur.fetchone()
    con.close()
    return row[0] if row and row[0] else "user"


# ====== 初期adminのブートストラップ（任意） ======
def ensure_admin_bootstrap() -> bool:
    """
    admin が未作成で、環境変数 ADMIN_PASSWORD が設定されている場合のみ作成。
    True: 作成した / False: 既に存在 or 未設定
    """
    create_users_table()
    admin_user = os.getenv("ADMIN_USERNAME", "admin")
    admin_pass = os.getenv("ADMIN_PASSWORD")
    if not admin_pass:
        return False

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT 1 FROM users WHERE username=?", (admin_user,))
    if cur.fetchone():
        con.close()
        return False

    hashed = bcrypt.hashpw(admin_pass.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    cur.execute(
        "INSERT INTO users (username, password, role) VALUES (?,?,?)",
        (admin_user, hashed, "admin"),
    )
    con.commit()
    con.close()
    return True
