import os
import sqlite3
import bcrypt

# ========== ローカル用（SQLite: ユーザー名＋パスワード認証＋role管理） ==========
DB_PATH = "users.db"

def create_users_table():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT,
            role TEXT
        )
    """)
    conn.commit()
    conn.close()

def signup_user(username, password, role="user"):
    create_users_table()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    hashed_pw = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
    try:
        cursor.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", (username, hashed_pw, role))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def login_user(username, password):
    create_users_table()
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
    create_users_table()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT role FROM users WHERE username = ?", (username,))
    result = cursor.fetchone()
    conn.close()
    if result and result[0]:
        return result[0]
    else:
        return "user"

def get_current_user():
    # ローカル用の仮ユーザーID返却
    return "local-user"

# ========== Google OAuth + Cloud SQL(PostgreSQL)対応 ==========

def get_or_create_user(email):
    """
    Cloud SQL (PostgreSQL) 用。メールアドレスでユーザー管理。
    - 存在すればそのまま返す
    - なければ role を判定してINSERTして返す
    """
    import psycopg2
    conn = psycopg2.connect(
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT")
    )
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            email TEXT PRIMARY KEY,
            role TEXT
        )
    """)
    c.execute("SELECT email, role FROM users WHERE email=%s", (email,))
    row = c.fetchone()
    if row:
        conn.close()
        return {"email": row[0], "role": row[1]}
    else:
        role = "admin" if email.endswith("@admin.com") else "user"
        c.execute("INSERT INTO users (email, role) VALUES (%s, %s)", (email, role))
        conn.commit()
        conn.close()
        return {"email": email, "role": role}

def verify_google_token(id_token_str, client_id):
    """
    Google IDトークン検証。正しければemailアドレスを返す。
    """
    from google.oauth2 import id_token
    from google.auth.transport import requests as google_requests
    try:
        id_info = id_token.verify_oauth2_token(id_token_str, google_requests.Request(), client_id)
        return id_info.get("email")
    except Exception:
        return None
