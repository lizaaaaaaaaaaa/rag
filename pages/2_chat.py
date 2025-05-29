import streamlit as st
import requests
import psycopg2
import os
from datetime import datetime

st.set_page_config(page_title="チャット", page_icon="💬", layout="wide")

# --- RAG APIのエンドポイント（環境変数） ---
API_URL = os.environ.get("API_URL", "https://rag-api-190389115361.asia-northeast1.run.app/chat")
if API_URL.endswith("/"):
    API_URL = API_URL.rstrip("/")

def post_chat(user_input):
    payload = {"question": user_input}
    print("========== [APIリクエストDebug] ==========")
    print("API_URL:", API_URL)
    print("payload:", payload)
    try:
        r = requests.post(API_URL, json=payload, timeout=30)
        print("status_code:", r.status_code)
        print("text:", r.text)
        if r.status_code == 200:
            res = r.json()
            return {
                "result": res.get("answer") or res.get("result"),
                "sources": res.get("sources", []),
            }
        else:
            return {"result": f"APIエラー: {r.status_code} / {r.text}", "sources": []}
    except Exception as e:
        print("リクエスト失敗:", e)
        return {"result": f"通信エラー: {e}", "sources": []}

# --- 未ログインガード ---
if "user" not in st.session_state:
    st.warning("ログインしてください。")
    st.stop()

# --- DB接続情報 ---
DB_HOST = os.environ.get("DB_HOST", "/cloudsql/rag-cloud-project:asia-northeast1:rag-postgres")
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
DB_NAME = os.environ.get("DB_NAME", "rag_db")
DB_USER = os.environ.get("DB_USER", "raguser")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "yourpassword")

# --- チャット履歴管理 ---
if "messages" not in st.session_state:
    st.session_state["messages"] = []

username = st.session_state["user"]
role = st.session_state.get("role", "user")

st.title("💬 チャット")

user_input = st.text_input("メッセージを入力してください", "")

if st.button("送信") and user_input.strip():
    api_response = post_chat(user_input)
    ai_response = api_response.get("result") or "応答エラー"
    sources = api_response.get("sources", [])

    # 履歴に追加
    st.session_state["messages"].append(("ユーザー", user_input))
    st.session_state["messages"].append(("アシスタント", ai_response))

    # --- DBに履歴保存 ---
    conn = None
    cursor = None
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
        )
        cursor = conn.cursor()
        # chat_logsテーブルに sourcesカラムが「なければ」sources抜きのINSERTにする
        cursor.execute(
            """
            INSERT INTO chat_logs (timestamp, username, role, question, answer)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (datetime.now(), username, role, user_input, ai_response),
        )
        conn.commit()
    except Exception as e:
        st.error(f"DB保存エラー: {e}")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

# --- チャット履歴の表示 ---
st.markdown("---")
st.subheader("チャット履歴")

for r, msg in st.session_state["messages"]:
    st.markdown(f"**{r}**: {msg}")
