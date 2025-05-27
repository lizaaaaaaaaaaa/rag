import os
import streamlit as st
import requests

# .env読込（本番環境なら不要）
if os.getenv("ENV") != "production":
    from dotenv import load_dotenv
    load_dotenv()

st.set_page_config(page_title="ログイン | RAG Fullstack App", layout="wide")
API_URL = os.getenv("API_URL", "http://localhost:8000")

# 1. 未ログイン時：Googleログイン案内
if "user" not in st.session_state:
    st.title("🔐 RAG Fullstack アプリ ログインページ")
    st.write("Googleログイン または 左メニューから「新規登録」でユーザー作成もできます。")

    # Google認証ボタン
    login_url = f"{API_URL}/auth/login/google"
    st.markdown(
        f'<a href="{login_url}" target="_self"><button style="font-size: 1.1em;">Googleでログイン</button></a>',
        unsafe_allow_html=True,
    )

    # Google認証コールバック
    query_params = st.experimental_get_query_params()
    if "code" in query_params:
        code = query_params["code"][0]
        r = requests.get(f"{API_URL}/auth/callback", params={"code": code})
        data = r.json()
        if "email" in data:
            st.session_state["user"] = data["email"]
            st.session_state["role"] = data.get("role", "user")
            st.experimental_set_query_params()  # URLのcode消す
            st.experimental_rerun()
        else:
            st.error(data.get("detail", "ログインに失敗しました"))

    # 手動ログイン(デバッグ・ローカル開発時)
    st.write("---")
    st.write("⬇️ もしくはユーザー名＋パスワードでログイン（開発用）")
    if st.button("ユーザー名・パスワードでログイン"):
        st.switch_page("0_login.py")
    st.stop()

# 2. ログイン済み
st.sidebar.success(f"✅ ログイン中: {st.session_state['user']}（{st.session_state.get('role', 'user')}）")
st.title("🌟 RAG Fullstack アプリへようこそ！")
st.write("左サイドバーから機能を選択してください。")

if st.sidebar.button("🔓 ログアウト"):
    del st.session_state["user"]
    st.session_state.pop("role", None)
    st.rerun()
