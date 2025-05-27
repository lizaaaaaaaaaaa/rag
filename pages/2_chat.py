import streamlit as st
import psycopg2
import os
from datetime import datetime

st.set_page_config(page_title="チャット", layout="wide")
st.title("チャット")

# DB接続情報（環境変数から取得）
db_host = os.environ.get("DB_HOST", "127.0.0.1")
db_port = int(os.environ.get("DB_PORT", "5432"))
db_name = os.environ.get("DB_NAME", "rag_db")
db_user = os.environ.get("DB_USER", "raguser")
db_password = os.environ.get("DB_PASSWORD", "yourpassword")


# セッションで履歴管理
if "messages" not in st.session_state:
    st.session_state["messages"] = []


user_input = st.text_input("メッセージを入力", "")


if st.button("送信") and user_input:
    # 仮の「AI応答」を作成（ここはRAGやAPI呼び出しに置き換えてOK）
    ai_response = f"（ダミー応答）あなたは「{user_input}」と入力しました。"


    # 履歴に追加
    st.session_state["messages"].append(("ユーザー", user_input))
    st.session_state["messages"].append(("アシスタント", ai_response))


    # DBに履歴を保存
    try:
        conn = psycopg2.connect(
            host=db_host, port=db_port, dbname=db_name, user=db_user, password=db_password
        )
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO chat_logs (timestamp, username, role, question, answer)
            VALUES (%s, %s, %s, %s, %s)
        """, (datetime.now(), "test_user", "user", user_input, ai_response))
        conn.commit()
        conn.close()
    except Exception as e:
        st.error(f"DB保存エラー: {e}")


# チャット履歴の表示
for role, msg in st.session_state["messages"]:
    st.markdown(f"**{role}**: {msg}")
