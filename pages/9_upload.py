# 9_upload.py

import streamlit as st
import os
import uuid
import traceback
import requests
from google.cloud import storage

# ページ設定は必ず最初の Streamlit 呼び出しとして配置
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

# ─────────────────────────────────────────────────────────────────────
# バックエンド API のベース URL
API_URL = os.environ.get("API_URL", "https://rag-api-190389115361.asia-northeast1.run.app")
if API_URL.endswith("/"):
    API_URL = API_URL.rstrip("/")

# GCS バケット名を環境変数から取得 (Cloud Run の環境変数に GCS_BUCKET_NAME を設定してください)
GCS_BUCKET_NAME = os.environ.get(
    "GCS_BUCKET_NAME",
    "run-sources-rag-cloud-project-asia-northeast1"
)

# ローカル保存用ディレクトリ (Streamlit 実行環境内)
os.makedirs("uploads", exist_ok=True)
# ─────────────────────────────────────────────────────────────────────


def save_upload_to_local(uploaded_file, save_dir="uploads"):
    """
    Streamlit のファイルアップローダーから受け取ったPDFを一旦ローカルに保存し、
    (ランダムなファイル名).pdf 形式で返す。
    """
    unique_filename = f"{uuid.uuid4().hex}.pdf"
    save_path = os.path.join(save_dir, unique_filename)
    with open(save_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return save_path, unique_filename


def upload_to_gcs(local_path, bucket_name, blob_name):
    """
    与えられたローカルパスのファイルをGCSバケットにアップロードする。
    戻り値として GCS URI (gs://bucket_name/blob_name) を返す。
    """
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    with open(local_path, "rb") as f:
        blob.upload_from_file(f, rewind=True)
    return f"gs://{bucket_name}/{blob_name}"


# ─── セッションステート管理 ───
if "upload_status" not in st.session_state:
    # init → アップロード前
    # uploaded → ローカル＆GCSにアップロード済
    # ingesting → ベクトルストア取り込み中
    # done → 取り込み完了→チャット可能
    st.session_state.upload_status = "init"

if "local_path" not in st.session_state:
    st.session_state.local_path = ""

if "unique_filename" not in st.session_state:
    st.session_state.unique_filename = ""

if "blob_name" not in st.session_state:
    st.session_state.blob_name = ""
# ───────────────────────────────────────


# === 1. アップロードフェーズ (/init) ===
if st.session_state.upload_status == "init":
    uploaded_file = st.file_uploader("PDFファイルを選択", type=["pdf"])
    if uploaded_file is not None:
        try:
            # ── (1) ローカルに保存 ──
            local_path, unique_filename = save_upload_to_local(uploaded_file)
            st.session_state.local_path = local_path
            st.session_state.unique_filename = unique_filename
            st.success(f"✅ ローカル保存成功: {local_path}")

            # ── (2) GCS にアップロード ──
            blob_name = f"uploads/{unique_filename}"
            gcs_uri = upload_to_gcs(local_path, GCS_BUCKET_NAME, blob_name)
            st.session_state.blob_name = blob_name
            st.success(f"✅ GCSアップロード成功: {blob_name}")

            # 状態を「uploaded」に変更して再実行
            st.session_state.upload_status = "uploaded"
            st.rerun()

        except Exception as e:
            st.error("❌ アップロード失敗")
            st.code(traceback.format_exc())


# === 2. 取り込み開始フェーズ (/uploaded) ===
elif st.session_state.upload_status == "uploaded":
    st.success("アップロード完了！")
    if st.button("このPDFをベクトルストアに取り込む"):
        # リクエストをベクトルストア取り込みモードへ
        st.session_state.upload_status = "ingesting"
        st.rerun()
    st.info("※ベクトルストアへの取り込みには数秒～数十秒かかる場合があります")


# === 3. 取り込み中フェーズ (/ingesting) ===
elif st.session_state.upload_status == "ingesting":
    try:
        with st.spinner("ベクトルストアに取り込み中...⏳"):
            # Cloud Run 上のバックエンド API（/upload/ingest）を呼び出す想定
            ingest_endpoint = f"{API_URL}/upload/ingest"
            payload = {"gcs_uri": f"gs://{GCS_BUCKET_NAME}/{st.session_state.blob_name}"}

            response = requests.post(ingest_endpoint, json=payload, timeout=600)
            if response.status_code != 200:
                # エラーが返ってきたら例外扱いにしてキャッチへ
                raise RuntimeError(f"バックエンド取り込みエラー: {response.status_code} / {response.text}")

        st.success("✅ ベクトルストア取り込み完了！")
        st.session_state.upload_status = "done"
        st.rerun()

    except Exception as e:
        st.error("❌ ベクトル化に失敗しました")
        st.code(traceback.format_exc())
        # ステータスを「uploaded」に戻して再挑戦できるように
        st.session_state.upload_status = "uploaded"


# === 4. チャットフェーズ (/done) ===
elif st.session_state.upload_status == "done":
    st.success("取り込み完了！このPDFの内容で質問できます")
    if st.button("最初からやり直す"):
        for key in ["upload_status", "local_path", "unique_filename", "blob_name"]:
            st.session_state.pop(key, None)
        st.rerun()

    st.subheader("💬 質問してみよう！")
    question = st.text_input("アップロードしたPDFの内容について質問")

    if question:
        try:
            with st.spinner("バックエンドへ質問を送信中...⏳"):
                payload = {"question": question, "username": st.session_state["user"]}
                # 頭に必ず末尾スラッシュを付与
                chat_url = f"{API_URL}/chat/"
                # デバッグ用に URL を表示
                print("=== API に POST する URL:", chat_url)
                st.write(f"API に POST する URL: {chat_url}")

                r = requests.post(chat_url, json=payload, timeout=60)

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
