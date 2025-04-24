import streamlit as st
from utils.auth import login_user, get_user_role

# ページ設定
st.set_page_config(page_title="RAG Fullstack App", layout="wide")

# ログインしていない場合はログイン画面を表示
if "user" not in st.session_state:
    login_user()
    st.stop()  # ログイン画面の後で描画を止める

# ログイン後の処理
role = get_user_role(st.session_state["user"])
st.sidebar.success(f"✅ ログイン中: {st.session_state['user']}（{role}）")

# メイン画面のUI
st.title("🌟 RAG Fullstack アプリへようこそ！")
st.write("左のサイドバーからページを選択してください。")
st.info("📤 アップロード、💬 チャット、📊 ダッシュボードなどを選べます。")

# ログアウト処理
if st.sidebar.button("🔓 ログアウト"):
    del st.session_state["user"]
    st.rerun()  # ← 新しい rerun 関数に変更（experimental ではない）


