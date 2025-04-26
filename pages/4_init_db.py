import streamlit as st
import sqlite3
import os

st.set_page_config(page_title="DB初期化", layout="centered")

st.title("🧹 chat_logs テーブルの初期化")

DB_FILE = "chat_logs.db"

# テーブルがすでに存在するか確認する関数
def check_table_exists():
    if not os.path.exists(DB_FILE):
        return False
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT name FROM sqlite_master WHERE type='table' AND name='chat_logs';
    """)
    result = cursor.fetchone()
    conn.close()
    return result is not None

# チェック実行
table_exists = check_table_exists()

# 状態によって表示を変える
if table_exists:
    st.success("✅ すでに chat_logs テーブルは存在しています！")
    st.button("✅ 初期化する", disabled=True)
else:
    st.warning("⚠️ chat_logs テーブルが存在しません。初期化が必要です！")
    if st.button("🛠️ 初期化する"):
        try:
            if os.path.exists(DB_FILE):
                os.remove(DB_FILE)

            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()

            cursor.execute("""
            CREATE TABLE chat_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                username TEXT NOT NULL,
                role TEXT NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                source TEXT
            )
            """)

            # ダミーデータ（任意で削除OK）
            sample_data = [
                ("2025-04-11 10:00:00", "admin", "user", "RAGとは？", "RAGは検索と生成を組み合わせた技術です。", "rag_intro.pdf (p2)"),
                ("2025-04-11 10:05:00", "user1", "user", "ローカルLLMは無料？", "ELYZAモデルなどは無料で使えます。", "llm_guide.pdf (p1)")
            ]
            cursor.executemany("""
                INSERT INTO chat_logs (timestamp, username, role, question, answer, source)
                VALUES (?, ?, ?, ?, ?, ?)
            """, sample_data)

            conn.commit()
            conn.close()

            st.success("✅ 初期化成功！ダミーデータも追加されました")
            st.experimental_rerun()  # 初期化後に画面リロードしてボタンを無効化する
        except Exception as e:
            st.error(f"❌ 初期化に失敗しました: {e}")
