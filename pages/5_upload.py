# pages/5_upload.py
import os
import io
import json
import uuid
import traceback
import requests
import streamlit as st

st.set_page_config(page_title="PDFアップロード & RAG質問", page_icon="📎", layout="centered")
st.title("📎 PDFアップロード ＆ 💬 RAG質問")

API_URL = os.getenv("API_URL", "http://localhost:8000").rstrip("/")
INGEST_URL = f"{API_URL}/upload/ingest"
CHAT_URL   = f"{API_URL}/chat"

def _auth_headers():
    user = st.session_state.get("user", "") or "anonymous"
    headers = {
        "X-User-Id": user,      # ← 同意ゲート用の識別
        "X-Platform": "web",    # ← ルーティング/緩和ルール用
    }
    # もし将来JWTを使うなら:
    token = st.session_state.get("jwt")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers

uploaded = st.file_uploader("PDFファイルを選択", type=["pdf"])
question = st.text_input("取り込み後にすぐ聞きたい質問（任意）")

if st.button("アップロードして取り込む", type="primary") and uploaded:
    try:
        pdf_bytes = uploaded.read()
        if not pdf_bytes:
            st.error("ファイルが空です。"); st.stop()

        # -------- 1) 取り込み（/upload/ingest） --------
        files = {"file": (uploaded.name, io.BytesIO(pdf_bytes), "application/pdf")}
        with st.spinner("取り込み中…（ベクトル化まで数十秒かかる場合があります）"):
            resp = requests.post(
                INGEST_URL, files=files, headers=_auth_headers(),
                timeout=(10, 600)  # connect, read
            )

        if resp.status_code != 200:
            st.error(f"ベクトル化に失敗しました\n{resp.status_code} / {resp.text}")
            st.stop()

        data = resp.json()
        st.success("取り込みが完了しました ✅")
        st.write({
            "filename": data.get("filename"),
            "gcs_path": data.get("gcs_path"),
            "added_docs": data.get("added_docs"),
            "message": data.get("message"),
        })

        # -------- 2) すぐ質問（任意） --------
        if question:
            payload = {
                "query": question,
                "user": st.session_state.get("user", "anonymous"),
                "platform": "web"
            }
            with st.spinner("RAGに質問中…"):
                r = requests.post(
                    CHAT_URL, json=payload, headers=_auth_headers(), timeout=(10, 60)
                )
            if r.status_code != 200:
                st.error(f"/chat エラー: {r.status_code} / {r.text}")
            else:
                ans = r.json()
                st.subheader("回答")
                st.write(ans.get("answer") or ans)
                if ans.get("sources"):
                    st.caption("出典:")
                    for s in ans["sources"]:
                        st.write(f"- {s}")

    except Exception as e:
        st.error("取り込み中にエラーが発生しました。ログを確認してください。")
        st.exception(e)
else:
    st.caption("PDFを選んで『アップロードして取り込む』を押すと、GCS保存→ベクトル化まで実行します。")

