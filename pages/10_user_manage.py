import streamlit as st
st.set_page_config(page_title="ユーザー管理", page_icon="👤", layout="wide")  # ←import直後！

import sqlite3
import pandas as pd

DB_FILE = "users.db"  # ユーザー管理用DB

# === ページタイトル・説明 ===
st.title("👤 ユーザー管理ページ（管理者専用）")
st.write("""
このページでは管理者ユーザーだけが、ユーザーアカウントの追加・削除・権限変更・パスワード変更を行えます。
""")

# 管理者のみ利用可
user = st.session_state.get("user", "")
if user != "admin":
    st.warning("管理者のみ利用できます。")
    st.stop()

# DB接続 & usersテーブル作成
conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE,
    password TEXT,
    role TEXT
)
""")

st.subheader("【ユーザー一覧】")
user_df = pd.read_sql_query("SELECT id, username, role FROM users", conn)
st.dataframe(user_df)

# ユーザー追加
with st.form(key="add_user_form"):
    new_username = st.text_input("新規ユーザー名")
    new_password = st.text_input("新規パスワード", type="password")
    new_role = st.selectbox("権限", ["user", "admin"])
    add_btn = st.form_submit_button("ユーザー追加")
    if add_btn and new_username and new_password:
        try:
            cursor.execute(
                "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                (new_username, new_password, new_role)
            )
            conn.commit()
            st.success(f"{new_username} を追加しました！")
            st.rerun()  # ←ここだけ変更！
        except Exception as e:
            st.error(f"追加失敗: {e}")

# ユーザー削除
del_user = st.selectbox("削除するユーザー", user_df["username"].tolist())
if st.button("ユーザー削除（注意！）"):
    cursor.execute("DELETE FROM users WHERE username = ?", (del_user,))
    conn.commit()
    st.success(f"{del_user} を削除しました。")
    st.rerun()  # ←ここも変更！

# パスワード変更
st.subheader("【パスワード変更】")
pw_user = st.selectbox("対象ユーザー", user_df["username"].tolist(), key="pw_user")
new_pw = st.text_input("新パスワード", type="password", key="pw_new")
if st.button("パスワード変更"):
    cursor.execute("UPDATE users SET password = ? WHERE username = ?", (new_pw, pw_user))
    conn.commit()
    st.success("パスワード変更しました！")

conn.close()
