import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime

st.set_page_config(page_title="履歴ダウンロード", layout="centered")

st.title("📥 チャット履歴ダウンロード")

DB_FILE = "chat_logs.db"

# 🔒 ログインチェック
if "user" not in st.session_state:
    st.warning("ログインしてください。")
    st.stop()

username = st.session_state["user"]
is_admin = username == "admin"  # 管理者判定

# DB接続
try:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    if is_admin:
        st.success("✅ 管理者モード：全ユーザー履歴ダウンロード可能")
        query = "SELECT * FROM chat_logs ORDER BY timestamp DESC"
        cursor.execute(query)
    else:
        st.info(f"👤 ユーザーモード：{username} さんの履歴のみダウンロード可能")
        query = "SELECT * FROM chat_logs WHERE username = ? ORDER BY timestamp DESC"
        cursor.execute(query, (username,))

    rows = cursor.fetchall()
    conn.close()

    if rows:
        df = pd.DataFrame(rows, columns=["ID", "日時", "ユーザー名", "ロール", "質問", "回答", "出典"])

        # 📄 ファイル名を自動生成（例: chat_logs_admin_20250426_1430.csv）
        now_str = datetime.now().strftime("%Y%m%d_%H%M")
        filename_base = f"chat_logs_{username}_{now_str}"

        # CSVダウンロードボタン
        csv = df.to_csv(index=False, encoding="utf-8-sig")
        st.download_button(
            label="📥 CSVでダウンロード",
            data=csv,
            file_name=f"{filename_base}.csv",
            mime="text/csv"
        )

        # JSONダウンロードボタン
        json = df.to_json(orient="records", force_ascii=False, indent=2)
        st.download_button(
            label="📥 JSONでダウンロード",
            data=json,
            file_name=f"{filename_base}.json",
            mime="application/json"
        )

    else:
        st.info("履歴データがありません。")

except Exception as e:
    st.error(f"❌ エラーが発生しました: {e}")
