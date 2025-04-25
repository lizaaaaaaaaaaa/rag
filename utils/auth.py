import streamlit as st

USER_CREDENTIALS = {
    "admin": "adminpass"
}

def login_user():
    st.title("🔐 ログインページ")

    if "login_attempted" not in st.session_state:
        st.session_state["login_attempted"] = False

    username = st.text_input("ユーザー名")
    password = st.text_input("パスワード", type="password")

    if st.button("ログイン"):
        if username in USER_CREDENTIALS and USER_CREDENTIALS[username] == password:
            st.session_state["user"] = username
            st.success("ログイン成功！")
            st.experimental_rerun()  # ← ここでも OK、安定性に問題なし
        else:
            st.session_state["login_attempted"] = True

    if st.session_state["login_attempted"]:
        st.error("ユーザー名またはパスワードが間違っています")

def get_user_role(username):
    return "admin"
