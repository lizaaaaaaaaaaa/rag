import os
import streamlit as st
import requests

# ローカル時のみ.env読み込み
if os.getenv("ENV") != "production":
    from dotenv import load_dotenv
    load_dotenv()

st.set_page_config(page_title="RAG Fullstack App", layout="wide")
API_URL = os.getenv("API_URL", "http://localhost:8000")

# 未ログイン時
if "user" not in st.session_state:
    st.title("🌟 RAG Fullstack アプリへようこそ！")
    st.write("Googleログインでご利用ください。")

    login_url = f"{API_URL}/auth/login/google"
    st.markdown(
        f'<a href="{login_url}" target="_self"><button style="font-size: 1.1em;">Googleでログイン</button></a>',
        unsafe_allow_html=True,
    )

    # Googleログイン認証後、クエリパラメータで ?code=xxxx でリダイレクトされることを想定
    # ↓URLにcodeが付いてたら/callbackを自動実行
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
    st.stop()

# ログイン済み
st.sidebar.success(f"✅ ログイン中: {st.session_state['user']}（{st.session_state['role']}）")
st.title("🌟 RAG Fullstack アプリへようこそ！")
st.write("左サイドバーからページを選んでください。")

if st.sidebar.button("🔓 ログアウト"):
    del st.session_state["user"]
    del st.session_state["role"]
    st.rerun()
