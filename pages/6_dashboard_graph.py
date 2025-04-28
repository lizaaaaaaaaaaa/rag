import streamlit as st
import sqlite3
import pandas as pd
import matplotlib.pyplot as plt

st.set_page_config(page_title="履歴グラフ可視化", layout="centered")
st.title("📈 チャット履歴グラフ可視化")

DB_FILE = "chat_logs.db"

# ログインチェック
if "user" not in st.session_state:
    st.warning("ログインしてください。")
    st.stop()

username = st.session_state["user"]
is_admin = username == "admin"

try:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    if is_admin:
        st.success("✅ 管理者モード：全履歴対象")
        cursor.execute("SELECT timestamp FROM chat_logs ORDER BY timestamp ASC")
    else:
        st.info(f"👤 {username} さんの履歴のみ対象")
        cursor.execute("SELECT timestamp FROM chat_logs WHERE username = ? ORDER BY timestamp ASC", (username,))

    timestamps = [row[0] for row in cursor.fetchall()]
    conn.close()

    if timestamps:
        # データ加工
        df = pd.DataFrame({"timestamp": pd.to_datetime(timestamps)})
        df['date'] = df['timestamp'].dt.date
        daily_counts = df.groupby('date').size()

        # グラフ表示
        st.subheader("🗓️ 日別の質問数推移")

        fig, ax = plt.subplots()
        daily_counts.plot(kind='bar', ax=ax)
        ax.set_xlabel("日付")
        ax.set_ylabel("質問数")
        ax.set_title("チャット質問数の推移")
        st.pyplot(fig)

    else:
        st.info("まだ履歴データがありません。")

except Exception as e:
    st.error(f"❌ エラーが発生しました: {e}")
