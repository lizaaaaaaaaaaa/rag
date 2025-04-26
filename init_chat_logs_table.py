import sqlite3
import os

DB_FILE = "RAG-LLM-Project/chat_logs.db"

# 既存ファイルがあれば削除
if os.path.exists(DB_FILE):
    os.remove(DB_FILE)

# 接続してテーブル作成
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

# ダミーデータ（任意）
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
print("✅ chat_logs テーブル作成＋データ挿入完了（新構造）")
