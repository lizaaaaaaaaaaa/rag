import streamlit as st

# シンプルなユーザー情報（本番ではDBや環境変数で管理推奨）
USER_CREDENTIALS = {
    "admin": "adminpass"
}

def login_user():
    st.title("🔐 ログインページ")

    username = st.text_input("ユーザー名")
    password = st.text_input("パスワード", type="password")

    if st.button("ログイン"):
        if username in USER_CREDENTIALS and USER_CREDENTIALS[username] == password:
            st.session_state["user"] = username
            st.success("ログイン成功！")
            st.experimental_rerun()
        else:
            st.error("ユーザー名またはパスワードが間違っています")

def get_user_role(username):
    return "admin"  # ここは今後複数ロール対応もできるように
