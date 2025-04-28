import streamlit as st
import sqlite3
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime

st.set_page_config(page_title="📈 チャット履歴グラフ可視化", layout="wide")

st.title("📈 チャット履歴グラフ可視化")

# セッションユーザー取得
user = st.session_state.get("user", "unknown")
is_admin = (user == "admin")

if is_admin:
    st.success("✅ 管理者モード：全履歴対象")
else:
    st.info(f"🧑‍💻 ユーザーモード：{user}さんの履歴のみ対象")

try:
    # データベース接続
    conn = sqlite3.connect("chat_logs.db")
    cursor = conn.cursor()

    # 管理者 or ユーザーごとにクエリ分岐
    if is_admin:
        query = "SELECT * FROM chat_logs"
        cursor.execute(query)
    else:
        query = "SELECT * FROM chat_logs WHERE username = ?"
        cursor.execute(query, (user,))

    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    conn.close()

    if rows:
        df = pd.DataFrame(rows, columns=columns)

        # ✅ 修正ポイント
        df["timestamp"] = pd.to_datetime(df["timestamp"])

        # 質問数推移（時間別）
        df["date"] = df["timestamp"].dt.date
        counts_per_day = df.groupby("date").size()

        st.subheader("🗓️ 質問数の推移（日別）")

        fig, ax = plt.subplots()
        counts_per_day.plot(kind="bar", ax=ax)
        ax.set_xlabel("日付")
        ax.set_ylabel("質問数")
        ax.set_title("チャット質問数の推移")
        plt.xticks(rotation=45)
        st.pyplot(fig)

    else:
        st.warning("⚠️ データがまだ存在しません。")

except Exception as e:
    st.error(f"❌ エラーが発生しました: {e}")
