import streamlit as st
import sqlite3
import pandas as pd

st.title("📊 チャット履歴ダッシュボード（出典付き）")

# SQLite接続
conn = sqlite3.connect("chat_logs.db")
cursor = conn.cursor()

# テーブル存在チェック
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='chat_logs'")
if cursor.fetchone():
    # 出典カラム（source）があるか確認して取得
    df = pd.read_sql_query("PRAGMA table_info(chat_logs)", conn)
    has_source_column = "source" in df["name"].values

    # チャット履歴を取得
    if has_source_column:
        query = "SELECT timestamp, username, role, question, answer, source FROM chat_logs ORDER BY timestamp DESC"
    else:
        query = "SELECT timestamp, username, role, question, answer FROM chat_logs ORDER BY timestamp DESC"

    df_logs = pd.read_sql_query(query, conn)

    if not df_logs.empty:
        st.dataframe(df_logs, use_container_width=True)

        st.download_button(
            label="📥 CSVでダウンロード",
            data=df_logs.to_csv(index=False).encode("utf-8-sig"),
            file_name="chat_logs.csv",
            mime="text/csv"
        )

        st.download_button(
            label="📥 JSONでダウンロード",
            data=df_logs.to_json(orient="records", force_ascii=False, indent=2),
            file_name="chat_logs.json",
            mime="application/json"
        )

        if has_source_column:
            st.info("📘 `source` カラムにはPDFファイル名やページ番号などの出典が記録されています。")
    else:
        st.warning("⚠️ チャット履歴がまだ存在しません。何か質問してから再度アクセスしてください。")
else:
    st.warning("⚠️ chat_logs テーブルが存在しません。先に初期化スクリプトを実行してください。")

conn.close()
