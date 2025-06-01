# 9_upload.py
import streamlit as st
import os
import uuid
import traceback
import requests
from google.cloud import storage

st.set_page_config(page_title="アップロード & RAG質問", page_icon="📤", layout="wide")

# --- 未ログインガード ---
if "user" not in st.session_state:
    st.warning("ログインしてください。")
    st.stop()

st.title("📤 PDFアップロード & 💬 RAG質問")
st.write("""
このページでは、PDFファイルをアップロードして、その内容に対してRAG（検索拡張生成）質問ができます。  
アップロードしたPDFは自動的にGCSへ保存され、ベクトルストアに取り込まれます。
""")

# バックエンド API のベース URL
API_URL = os.environ.get("API_URL", "https://rag-api-190389115361.asia-northeast1.run.app")
if API_URL.endswith("/"):
    API_URL = API_URL.rstrip("/")

GCS_BUCKET_NAME = os.environ.get("GCS_BUCKET_NAME", "run-sources-rag-cloud-project-asia-northeast1")
os.makedirs("uploads", exist_ok=True)


def save_upload_to_local(uploaded_file, save_dir="uploads"):
    unique_filename = f"{uuid.uuid4().hex}.pdf"
    save_path = os.path.join(save_dir, unique_filename)
    with open(save_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return save_path, unique_filename


def upload_to_gcs(local_path, bucket_name, blob_name):
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    with open(local_path, "rb") as f:
        blob.upload_from_file(f, rewind=True)
    return f"gs://{bucket_name}/{blob_name}"


# === セッションステート管理 ===
if "upload_status" not in st.session_state:
    st.session_state.upload_status = "init"   # init, uploaded, ingesting, done
if "local_path" not in st.session_state:
    st.session_state.local_path = ""
if "unique_filename" not in st.session_state:
    st.session_state.unique_filename = ""
if "blob_name" not in st.session_state:
    st.session_state.blob_name = ""

# === 1. アップロードフェーズ ===
if st.session_state.upload_status == "init":
    uploaded_file = st.file_uploader("PDFファイルを選択", type=["pdf"])
    if uploaded_file is not None:
        try:
            # 1. ローカル保存
            local_path, unique_filename = save_upload_to_local(uploaded_file)
            st.session_state.local_path = local_path
            st.session_state.unique_filename = unique_filename
            st.success(f"✅ ローカル保存成功: {local_path}")

            # 2. GCSアップロード
            blob_name = f"uploads/{unique_filename}"
            upload_to_gcs(local_path, GCS_BUCKET_NAME, blob_name)
            st.session_state.blob_name = blob_name
            st.success(f"✅ GCSアップロード成功: {blob_name}")

            # ステータスを「uploaded」に変えてリロード
            st.session_state.upload_status = "uploaded"
            st.rerun()

        except Exception as e:
            st.error("❌ アップロード失敗")
            st.code(traceback.format_exc())

# === 2. 取り込み開始フェーズ ===
elif st.session_state.upload_status == "uploaded":
    st.success("アップロード完了！")
    if st.button("このPDFをベクトルストアに取り込む"):
        st.session_state.upload_status = "ingesting"
        st.rerun()
    st.info("※ベクトルストアへの取り込みには数秒～数十秒かかる場合があります")

# === 3. 取り込み中フェーズ ===
elif st.session_state.upload_status == "ingesting":
    try:
        with st.spinner("ベクトルストアに取り込み中...⏳"):
            # ingest_pdf_to_vectorstore は rag.ingested_text に定義されている想定
            from rag.ingested_text import ingest_pdf_to_vectorstore
            ingest_pdf_to_vectorstore(st.session_state.local_path)

        st.success("✅ ベクトルストア取り込み完了！")
        st.session_state.upload_status = "done"
        st.rerun()

    except Exception as e:
        st.error("❌ ベクトル化に失敗しました")
        st.code(traceback.format_exc())
        st.session_state.upload_status = "uploaded"  # ステータスを戻す

# === 4. チャットフェーズ ===
elif st.session_state.upload_status == "done":
    st.success("取り込み完了！このPDFの内容で質問できます")
    if st.button("最初からやり直す"):
        for key in ["upload_status", "local_path", "unique_filename", "blob_name"]:
            st.session_state.pop(key, None)
        st.rerun()

    st.subheader("💬 質問してみよう！")
    question = st.text_input("アップロードしたPDFの内容について質問")

    if question:
        # ここでは「バックエンド API (/chat/) へ POST するだけ」に切り替え
        try:
            with st.spinner("バックエンドへ質問を送信中...⏳"):
                payload = {"question": question, "username": st.session_state["user"]}
                url = f"{API_URL}/chat/"
                # デバッグ用に URL を表示
                print("=== APIにPOSTするURL:", url)
                st.write(f"API に POST する URL: {url}")

                r = requests.post(url, json=payload, timeout=60)
        except Exception as e:
            st.error(f"通信エラー: {e}")
            st.stop()

        if r.status_code == 200:
            res_json = r.json()
            st.write(f"📘 回答: {res_json.get('answer') or '❌ 応答が見つかりませんでした'}")
            sources = res_json.get("sources", [])
            if sources:
                st.write("📎 出典:")
                for entry in sources:
                    meta = entry.get("metadata", {})
                    source = meta.get("source", "不明")
                    page = meta.get("page", "?")
                    st.write(f"- {source} (p{page})")
        else:
            st.error(f"API エラー: {r.status_code} / {r.text}")
