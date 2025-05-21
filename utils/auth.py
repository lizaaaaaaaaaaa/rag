# ✅ 新しい構成：utils/auth.py（共通関数のみを残す）
import sqlite3
import bcrypt

DB_PATH = "users.db"

def create_users_table():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT
        )
    """)
    conn.commit()
    conn.close()

def signup_user(username, password):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    hashed_pw = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
    try:
        cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, hashed_pw))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def login_user(username, password):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT password FROM users WHERE username=?", (username,))
    result = cursor.fetchone()
    conn.close()

    if result and bcrypt.checkpw(password.encode(), result[0]):
        return True
    else:
        return False

def get_user_role(username):
    return "user"

def verify_google_token(id_token_str, client_id):
    from google.oauth2 import id_token
    from google.auth.transport import requests as google_requests
    try:
        id_info = id_token.verify_oauth2_token(id_token_str, google_requests.Request(), client_id)
        return id_info.get("email")
    except Exception:
        return None
def get_current_user():
    # ローカル用の仮ユーザーID返却
    return "local-user"
