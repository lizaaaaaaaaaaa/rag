import os
import uuid
import streamlit as st
import traceback
from google.cloud import storage
from rag.ingested_text import ingest_pdf_to_vectorstore, load_vectorstore, get_rag_chain

# --- ここから未ログインガード ---
if "user" not in st.session_state:
    st.warning("ログインしてください。")
    st.stop()
# --- ここまで ---

# GCSバケット名は環境変数優先（なければデフォルト）
GCS_BUCKET_NAME = os.environ.get("GCS_BUCKET_NAME", "run-sources-rag-cloud-project-asia-northeast1")

# GCSアップロード関数
def upload_to_gcs(file, bucket_name, blob_name):
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.upload_from_file(file, rewind=True)
    return f"gs://{bucket_name}/{blob_name}"

st.set_page_config(page_title="アップロード & RAG質問", layout="wide")
st.title("📤 PDFアップロード & 💬 RAG質問")
st.write("アップロードしたPDFの内容から質問できます")

# ファイルアップロード
uploaded_file = st.file_uploader("PDFファイルを選択", type=["pdf"])

if uploaded_file is not None:
    # ファイル名をUUID＋拡張子で生成（日本語ファイル名にも安心）
    unique_filename = f"{uuid.uuid4().hex}.pdf"
    blob_name = f"uploads/{unique_filename}"

    # GCSにアップロード
    try:
        with st.spinner("GCSにアップロード中..."):
            gcs_uri = upload_to_gcs(uploaded_file, GCS_BUCKET_NAME, blob_name)
        st.success(f"✅ GCSアップロード成功: {blob_name}")
    except Exception as e:
        st.error("❌ GCSへのアップロードに失敗しました")
        st.code(traceback.format_exc())
        st.stop()

    # GCSへのアップロードが完了したらベクトルストアに取り込み
    try:
        with st.spinner("ベクトルストア取り込み中...⏳"):
            # GCSから一時ファイルとしてダウンロードしてingestする方法もOK
            # ここは ingest_pdf_to_vectorstore(blob_name or gcs_uri) に応じて修正
            # ingest_pdf_to_vectorstore関数がGCS対応していない場合は一時DLも要検討
            ingest_pdf_to_vectorstore(blob_name)  # ←必要に応じてパスを修正
        st.success("✅ ベクトルストア取り込み完了！")
    except Exception as e:
        st.error("❌ ベクトル化に失敗しました")
        st.code(traceback.format_exc())
        st.stop()

    # 💬 質問UI
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
