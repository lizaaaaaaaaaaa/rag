# ✅ 完成版: 6_dashboard_graph.py
import streamlit as st
import pandas as pd
import sqlite3
import matplotlib.pyplot as plt

# DBファイルパス
DB_FILE = "chat_logs.db"

st.set_page_config(page_title="チャット履歴グラフ可視化", layout="wide")

st.title("📈 チャット履歴グラフ可視化")

# 管理者モード切り替え
is_admin = st.checkbox("管理者モード：全履歴対象", value=False)

try:
    # DB接続
    conn = sqlite3.connect(DB_FILE)
    query = "SELECT timestamp, username FROM chat_logs"
    df = pd.read_sql_query(query, conn)

    if not df.empty:
        # ✅ タイムスタンプ列をdatetime型に変換 (ISO8601対応！)
        df["timestamp"] = pd.to_datetime(df["timestamp"], format="ISO8601")

        # ユーザー別フィルタ
        if not is_admin:
            current_user = st.session_state.get("user")
            if current_user:
                df = df[df["username"] == current_user]

        if not df.empty:
            # 日別に集計
            df["date"] = df["timestamp"].dt.date
            daily_counts = df.groupby("date").size()

            # グラフ描画
            st.subheader("📅 質問数の推移")
            fig, ax = plt.subplots()
            daily_counts.plot(kind="bar", ax=ax)
            ax.set_xlabel("日付")
            ax.set_ylabel("質問数")
            ax.set_title("日別 質問数の推移")
            st.pyplot(fig)
        else:
            st.info("🔍 データがありません。チャットを開始してください！")
    else:
        st.info("🔍 データが存在しません。チャット履歴を作成してください！")
except Exception as e:
    st.error(f"❌ エラーが発生しました: {e}")
finally:
    conn.close()
