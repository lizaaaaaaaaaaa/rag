import streamlit as st
import sqlite3
import pandas as pd
import matplotlib.pyplot as plt

st.set_page_config(page_title="チャット履歴グラフ可視化", layout="wide")

st.title("📈 チャット履歴グラフ可視化")

# DB接続
DB_FILE = "chat_logs.db"
conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()

# ログイン中ユーザー取得
current_user = st.session_state.get("user", "unknown")

# 管理者判定
is_admin = current_user == "admin"

# 管理者なら全履歴、それ以外は自分だけ
if is_admin:
    st.success("✅ 管理者モード：全履歴対象")
    query = "SELECT * FROM chat_logs"
    params = ()
else:
    query = "SELECT * FROM chat_logs WHERE username = ?"
    params = (current_user,)

# データ取得
df = pd.read_sql_query(query, conn, params=params)

if df.empty:
    st.warning("⚠️ データが存在しません")
else:
    # 🔥 ここを修正！（format指定なしにする）
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    # 日別集計
    df["date"] = df["timestamp"].dt.date
    daily_counts = df.groupby("date").size()

    st.subheader("🗓️ 日別 質問数の推移")

    fig, ax = plt.subplots()
    daily_counts.plot(kind="bar", ax=ax)
    ax.set_xlabel("日付")
    ax.set_ylabel("質問数")
    ax.set_title("日別 質問数推移")
    st.pyplot(fig)

conn.close()
