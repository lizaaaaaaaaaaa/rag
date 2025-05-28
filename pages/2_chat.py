import streamlit as st
st.set_page_config(page_title="チャット", page_icon="💬", layout="wide")

import requests
import psycopg2
import os
from datetime import datetime

# --- RAG APIのエンドポイント ---
API_URL = os.environ.get("https://rag-api-190389115361.asia-northeast1.run.app")  # 必要なら環境変数に

def post_chat(user_input, username):
    payload = {"question": user_input}
    try:
        r = requests.post(API_URL, json=payload, timeout=30)
        if r.status_code == 200:
            res = r.json()
            # FastAPI側で "answer" or "result" 返却に対応
            return {"result": res.get("answer") or res.get("result"), "sources": res.get("sources", [])}
        else:
            return {"result": f"エラー: {r.status_code} / {r.text}"}
    except Exception as e:
        return {"result": f"通信エラー: {e}"}

# --- 未ログインガード ---
if "user" not in st.session_state:
    st.warning("ログインしてください。")
    st.stop()

# DB接続情報（環境変数から取得）
db_host = os.environ.get("DB_HOST", "10.19.80.4")
db_port = int(os.environ.get("DB_PORT", "5432"))
db_name = os.environ.get("DB_NAME", "rag_db")
db_user = os.environ.get("DB_USER", "raguser")
db_password = os.environ.get("DB_PASSWORD", "yourpassword")

# セッションで履歴管理
if "messages" not in st.session_state:
    st.session_state["messages"] = []

# ログインユーザー名取得
username = st.session_state.get("user", "local-user")
role = st.session_state.get("role", "user")

st.title("💬 チャット")

user_input = st.text_input("メッセージを入力してください", "")

if st.button("送信") and user_input:
    # ↓API経由のRAG応答
    api_response = post_chat(user_input, username)
    ai_response = api_response.get("result") or str(api_response)

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
        """, (datetime.now(), username, role, user_input, ai_response))
        conn.commit()
        conn.close()
    except Exception as e:
        st.error(f"DB保存エラー: {e}")

# チャット履歴の表示
for r, msg in st.session_state["messages"]:
    st.markdown(f"**{r}**: {msg}")
