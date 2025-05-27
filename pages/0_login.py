import streamlit as st
st.set_page_config(page_title="ログイン", page_icon="🔑", layout="wide")  # ←import直後

from utils.auth import login_user, get_user_role, create_users_table
create_users_table()

if "user" not in st.session_state:
    st.title("🔑 ログインページ")
    username = st.text_input("ユーザー名")
    password = st.text_input("パスワード", type="password")

    if st.button("ログイン"):
        result = login_user(username, password)
        if result:
            st.session_state["user"] = username
            st.session_state["role"] = get_user_role(username)
            st.success(f"✅ ようこそ {username} さん！")
            st.rerun()
        else:
            st.error("❌ ログイン失敗。ユーザー名かパスワードが違います。")
    st.stop()

# ↓ ログイン済み
st.sidebar.success(f"✅ ログイン中: {st.session_state['user']}（{st.session_state.get('role', 'user')}）")
st.title("🌟 RAG Fullstack アプリへようこそ！")
st.write("左サイドバーからページを選んでください。")
if st.sidebar.button("🔓 ログアウト"):
    del st.session_state["user"]
    st.session_state.pop("role", None)
    st.rerun()
