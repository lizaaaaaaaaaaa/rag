import streamlit as st
import requests
import os

# --- デバッグ用：環境変数 API_URL の中身を画面に表示 ---
if "DEBUG_SHOW_API_URL" not in st.session_state:
    api_url_debug = os.environ.get("API_URL", "API_URL が設定されていません")
    st.write(f"DEBUG: API_URL = {api_url_debug}")
    st.session_state["DEBUG_SHOW_API_URL"] = True
# -----------------------------------------------------------

st.set_page_config(page_title="チャット", page_icon="💬", layout="wide")

# .env の API_URL は「末尾スラッシュなし」で指定する想定
API_URL = os.environ.get("API_URL", "https://rag-api-190389115361.asia-northeast1.run.app")
if API_URL.endswith("/"):
    API_URL = API_URL.rstrip("/")

def post_chat(user_input, username):
    payload = {"question": user_input, "username": username}

    # 末尾にスラッシュをつけて POST /chat/ を直接叩く
    url = f"{API_URL}/chat/"

    # === Debug: びしっと URL を確認 ===
    print("=== API に POST する URL:", url)
    st.write(f"API に POST する URL: {url}")

    try:
        r = requests.post(url, json=payload, timeout=30)
        if r.status_code == 200:
            res = r.json()
            return {
                "result": res.get("answer") or res.get("result"),
                "sources": res.get("sources", []),
            }
        else:
            return {"result": f"API エラー: {r.status_code} / {r.text}", "sources": []}
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
st.write("Chatページ動いてるよ")  # デバッグ用

user_input = st.text_input("メッセージを入力してください", "")

if st.button("送信") and user_input.strip():
    st.write("API呼び出し直前！")  # デバッグ用
    api_response = post_chat(user_input, username)
    ai_response = api_response.get("result") or "応答エラー"
    sources = api_response.get("sources", [])
    st.session_state["messages"].append(("ユーザー", user_input))
    st.session_state["messages"].append(("アシスタント", ai_response))

st.markdown("---")
st.subheader("チャット履歴")
for r, msg in st.session_state["messages"]:
    st.markdown(f"**{r}**: {msg}")
