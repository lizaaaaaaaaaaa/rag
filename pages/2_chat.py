import streamlit as st
import requests
import os
from datetime import datetime

st.set_page_config(page_title="チャット", page_icon="💬", layout="wide")

API_URL = os.environ.get("API_URL", "https://rag-api-190389115361.asia-northeast1.run.app/chat")

if API_URL.endswith("/"):
    API_URL = API_URL.rstrip("/")

def post_chat(user_input, username):
    payload = {"question": user_input, "username": username}
    try:
        r = requests.post(API_URL, json=payload, timeout=30)
        if r.status_code == 200:
            res = r.json()
            return {
                "result": res.get("answer") or res.get("result"),
                "sources": res.get("sources", []),
            }
        else:
            return {"result": f"APIエラー: {r.status_code} / {r.text}", "sources": []}
    except Exception as e:
        return {"result": f"通信エラー: {e}", "sources": []}

# --- 未ログインガード ---
if "user" not in st.session_state:
    st.warning("ログインしてください。")
    st.stop()

if "messages" not in st.session_state:
    st.session_state["messages"] = []

username = st.session_state["user"]

st.title("💬 チャット")
st.write("Chatページ動いてるよ")  # ← デバッグ用！

user_input = st.text_input("メッセージを入力してください", "")

if st.button("送信") and user_input.strip():
    st.write("API呼び出し直前！")  # ← デバッグ用
    api_response = post_chat(user_input, username)
    ai_response = api_response.get("result") or "応答エラー"
    sources = api_response.get("sources", [])
    st.session_state["messages"].append(("ユーザー", user_input))
    st.session_state["messages"].append(("アシスタント", ai_response))

st.markdown("---")
st.subheader("チャット履歴")
for r, msg in st.session_state["messages"]:
    st.markdown(f"**{r}**: {msg}")
