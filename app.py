import streamlit as st
from utils.auth import get_user_role, create_users_table

st.set_page_config(page_title="RAG Fullstack App", layout="wide")

create_users_table()

# ガード：未ログインならログインページへリダイレクト
if "user" not in st.session_state:
    st.switch_page("0_login.py")  # バージョンによっては案内文でもOK
    st.stop()

# ログイン成功後
role = get_user_role(st.session_state["user"])
st.sidebar.success(f"✅ ログイン中: {st.session_state['user']}（{role}）")

st.title("🌟 RAG Fullstack アプリへようこそ！")
st.write("左サイドバーからページを選んでください。")

if st.sidebar.button("🔓 ログアウト"):
    del st.session_state["user"]
    st.rerun()
