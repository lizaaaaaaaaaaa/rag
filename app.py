import os
import streamlit as st
import requests

# .env読み込み（開発環境のみ）
if os.getenv("ENV") != "production":
    from dotenv import load_dotenv
    load_dotenv()

# 日本語タイトル＋ページアイコン（🏠）で設定
st.set_page_config(page_title="ホーム | RAG Fullstack アプリ", page_icon="🏠", layout="wide")
API_URL = os.getenv("API_URL", "https://rag-api-190389115361.asia-northeast1.run.app")

# 2. ログイン済みユーザー
user = st.session_state.get('user')
role = st.session_state.get('role', 'user')
if user:
    st.sidebar.success(f"✅ ログイン中: {user}（{role}）")
    st.title("🏠 RAG Fullstack アプリ ホームページ")
    st.write("""
    RAG Fullstack アプリへようこそ！

    左のメニューから「チャット」「ダッシュボード」「FAQタグ管理」など各機能ページにアクセスできます。
    使い方などは上部メニューからもご確認いただけます。
    """)
    if st.sidebar.button("🔓 ログアウト"):
        del st.session_state["user"]
        st.session_state.pop("role", None)
        st.session_state.pop("token", None)
        st.rerun()
else:
    st.stop()
