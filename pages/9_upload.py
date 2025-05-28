import streamlit as st
st.set_page_config(page_title="アップロード & RAG質問", page_icon="📤", layout="wide")

import os
import uuid
import traceback
from google.cloud import storage
from rag.ingested_text import ingest_pdf_to_vectorstore, load_vectorstore, get_rag_chain

# --- 未ログインガード ---
if "user" not in st.session_state:
    st.warning("ログインしてください。")
    st.stop()
# --- ここまで ---

st.title("📤 PDFアップロード & 💬 RAG質問")
st.write("""
このページでは、PDFファイルをアップロードして、その内容に対してRAG（検索拡張生成）質問ができます。
アップロードしたPDFは自動的にGCSへ保存され、ベクトルストアに取り込まれます。
""")

GCS_BUCKET_NAME = os.environ.get("GCS_BUCKET_NAME", "run-sources-rag-cloud-project-asia-northeast1")

# === 必要なら "uploads" ディレクトリを作成 ===
os.makedirs("uploads", exist_ok=True)

def save_upload_to_local(uploaded_file, save_dir="uploads"):
    # 拡張子安全化（例: .pdf 以外アップロード不可にしてる前提）
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

uploaded_file = st.file_uploader("PDFファイルを選択", type=["pdf"])

if uploaded_file is not None:
    # 1. ローカル保存
    try:
        local_path, unique_filename = save_upload_to_local(uploaded_file)
        st.success(f"✅ ローカル保存成功: {local_path}")
    except Exception as e:
        st.error("❌ ローカル保存に失敗しました")
        st.code(traceback.format_exc())
        st.stop()

    # 2. GCSにアップロード
    blob_name = f"uploads/{unique_filename}"
    try:
        with st.spinner("GCSにアップロード中..."):
            gcs_uri = upload_to_gcs(local_path, GCS_BUCKET_NAME, blob_name)
        st.success(f"✅ GCSアップロード成功: {blob_name}")
    except Exception as e:
        st.error("❌ GCSへのアップロードに失敗しました")
        st.code(traceback.format_exc())
        st.stop()

    # 3. ベクトルストアに取り込み（ローカルパスで！）
    try:
        with st.spinner("ベクトルストア取り込み中...⏳"):
            ingest_pdf_to_vectorstore(local_path)  # ここは「ローカルパス」
        st.success("✅ ベクトルストア取り込み完了！")
    except Exception as e:
        st.error("❌ ベクトル化に失敗しました")
        st.code(traceback.format_exc())
        st.stop()

    # 4. 💬 質問UI
    st.subheader("💬 質問してみよう！")
    question = st.text_input("アップロードしたPDFの内容について質問")

    if question:
        try:
            with st.spinner("ベクトルストア読込中..."):
                vectorstore = load_vectorstore()
        except Exception as e:
            st.error("❌ ベクトルストアの読み込みに失敗しました")
            st.code(traceback.format_exc())
            st.stop()

        try:
            with st.spinner("RAGチェーン構築中..."):
                rag_chain = get_rag_chain(vectorstore, return_source=True, question=question)
        except Exception as e:
            st.error("❌ RAGチェーンの構築に失敗しました")
            st.code(traceback.format_exc())
            st.stop()

        try:
            with st.spinner("回答生成中..."):
                result = rag_chain.invoke({"question": question})
            st.write(f"📘 回答: {result.get('result', '❌ 回答が見つかりませんでした')}")
            if result.get("source_documents"):
                st.write("📎 出典:")
                for doc in result["source_documents"]:
                    source = doc.metadata.get("source", "不明")
                    page = doc.metadata.get("page", "?")
                    st.write(f"- {source} (p{page})")
        except Exception as e:
            st.error("❌ 回答生成中にエラーが発生しました")
            st.code(traceback.format_exc())
