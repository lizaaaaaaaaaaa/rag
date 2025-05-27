# pages/0_login.py
import streamlit as st
from utils.auth import login_user, get_user_role, create_users_table

st.set_page_config(page_title="ログイン", layout="wide")

create_users_table()

if "user" not in st.session_state:
    st.title("🔐 ログインページ")
    username = st.text_input("ユーザー名")
    password = st.text_input("パスワード", type="password")

    if st.button("ログイン"):
        result = login_user(username, password)
        st.write(f"login_userの結果: {result}")  # デバッグ用（動作確認したら削除OK）
        if result:
            st.session_state["user"] = username
            st.success(f"✅ ようこそ {username} さん！")
            st.rerun()
        else:
            st.error("❌ ログイン失敗。ユーザー名かパスワードが違います。")

    # 🔗 新規登録ページへ移動ボタン
    if st.button("新規ユーザー登録はこちら"):
        st.switch_page("1_signup.py")  # pages/1_signup.pyを想定（数字で並び替えやすい）
    st.stop()

role = get_user_role(st.session_state["user"])
st.sidebar.success(f"✅ ログイン中: {st.session_state['user']}（{role}）")
st.title("🌟 RAG Fullstack アプリへようこそ！")
st.write("左サイドバーからページを選んでください。")
if st.sidebar.button("🔓 ログアウト"):
    del st.session_state["user"]
    st.rerun()


