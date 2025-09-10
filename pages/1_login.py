import streamlit as st
from unicodedata import normalize
from utils.auth import ensure_admin_bootstrap, login_user, get_user_role, get_users, get_db_path

st.set_page_config(page_title="ログイン", page_icon="🔐", layout="centered")

# --- 起動時に admin を自動生成（ADMIN_PASSWORD があれば、未作成時のみ）---
created = ensure_admin_bootstrap()
st.caption("✅ admin を自動作成（ADMIN_PASSWORD 使用）" if created else "ℹ️ admin 作成はスキップ（既存 or ADMIN_PASSWORD 未設定）")

st.title("🔐 ログイン")

# (任意) デバッグ表示（確認できたらOFF推奨）
with st.expander("デバッグ（暫定）", expanded=False):
    st.write(f"DB_PATH = `{get_db_path()}`")
    try:
        users = get_users()
        st.write(f"users 件数: {len(users)}")
        st.write("admin: 存在します" if any(u.get("username") == "admin" for u in users) else "admin: なし")
    except Exception as e:
        st.write("ユーザー取得で例外:", str(e))

# 入力
username_in = st.text_input("ユーザー名")
password_in = st.text_input("パスワード", type="password")

# 同じ正規化で統一
username = (username_in or "").strip().lower()
password = normalize("NFC", password_in or "")

if st.button("ログイン"):
    if login_user(username, password):
        st.session_state["user"] = username
        st.session_state["role"] = get_user_role(username)
        st.success("ログイン成功！")
        st.rerun()
    else:
        st.error("ユーザー名またはパスワードが違います。")
