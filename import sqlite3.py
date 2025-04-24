import sqlite3

db_path = "D:/RAG-LLM-Project/streamlit_rag_fullstack_ultimate/chat_logs.db"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()

print("📋 DB内のテーブル一覧:", tables)

conn.close()
