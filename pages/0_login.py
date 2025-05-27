# pages/0_login.py
import streamlit as st
from utils.auth import login_user, get_user_role, create_users_table

st.set_page_config(page_title="ユーザーログイン", layout="wide")

create_users_table()

if "user" not in st.session_state:
    st.title("🔐 ユーザーログイン")
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

    if st.button("新規ユーザー登録はこちら"):
        st.switch_page("1_signup.py")
    st.stop()

st.sidebar.success(f"✅ ログイン中: {st.session_state['user']}（{st.session_state.get('role', 'user')}）")
st.title("🌟 RAG Fullstack アプリへようこそ！")
st.write("左サイドバーからページを選んでください。")
if st.sidebar.button("🔓 ログアウト"):
    del st.session_state["user"]
    st.session_state.pop("role", None)
    st.rerun()
