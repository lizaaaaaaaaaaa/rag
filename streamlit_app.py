import streamlit as st
from utils.auth import login_user, get_user_role, create_users_table

st.set_page_config(page_title="RAG Fullstack App", layout="wide")

create_users_table()

if "user" not in st.session_state:
    st.title("🔐 ログインページ")
    username = st.text_input("ユーザー名")
    password = st.text_input("パスワード", type="password")

    if st.button("ログイン"):
        if login_user(username, password):
            st.success(f"✅ ようこそ {username} さん！")
            st.experimental_rerun()
        else:
            st.error("❌ ログイン失敗。ユーザー名かパスワードが違います。")
    st.stop()

# ログイン成功後
role = get_user_role(st.session_state["user"])
st.sidebar.success(f"✅ ログイン中: {st.session_state['user']}（{role}）")

st.title("🌟 RAG Fullstack アプリへようこそ！")
st.write("左サイドバーからページを選んでください。")

if st.sidebar.button("🔓 ログアウト"):
    del st.session_state["user"]
    st.experimental_rerun()

