import streamlit as st
from utils.auth import login_user, get_user_role

st.set_page_config(page_title="RAG Fullstack App", layout="wide")

# ユーザーログイン処理を呼び出し
if "user" not in st.session_state:
    login_user()
    st.stop()  # ← ここを追加！

# ロール取得
role = get_user_role(st.session_state["user"])
st.sidebar.success(f"✅ ログイン中: {st.session_state['user']}（{role}）")

# メインページの内容（必要に応じてカスタマイズ）
st.title("🌟 RAG Fullstack アプリへようこそ！")

st.write("左のサイドバーからページを選択してください。")
st.info("📤 アップロード、💬 チャット、📊 ダッシュボードなどを選べます。")

# ログアウトボタン
if st.sidebar.button("🔓 ログアウト"):
    del st.session_state["user"]
    st.experimental_rerun()

