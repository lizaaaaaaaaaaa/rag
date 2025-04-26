import streamlit as st
import sqlite3
import pandas as pd

st.set_page_config(page_title="ダッシュボード", layout="wide")
st.title("📊 チャット履歴ダッシュボード（出典付き）")

DB_FILE = "chat_logs.db"

# 🔒 ログインチェック
if "user" not in st.session_state:
    st.warning("ログインしてください。")
    st.stop()

username = st.session_state["user"]
is_admin = username == "admin"  # ここで admin 判定

try:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    if is_admin:
        st.success("✅ 管理者モード：すべてのユーザーの履歴を表示中")
        cursor.execute("SELECT * FROM chat_logs ORDER BY timestamp DESC")
    else:
        st.info(f"👤 ユーザーモード：{username} さんの履歴のみ表示中")
        cursor.execute("SELECT * FROM chat_logs WHERE username = ? ORDER BY timestamp DESC", (username,))

    rows = cursor.fetchall()
    conn.close()

    if rows:
        df = pd.DataFrame(rows, columns=["ID", "日時", "ユーザー名", "ロール", "質問", "回答", "出典"])
        st.dataframe(df, use_container_width=True)
    else:
        st.info("履歴がまだありません。")

except Exception as e:
    st.error(f"エラーが発生しました: {e}")
