import streamlit as st
from google.cloud import storage

GCS_BUCKET_NAME = "run-sources-rag-cloud-project-asia-northeast1"

def upload_to_gcs(file, bucket_name, blob_name):
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.upload_from_file(file, rewind=True)
    return f"gs://{bucket_name}/{blob_name}"

st.title("GCSアップロードテスト")

uploaded_file = st.file_uploader("PDFファイルをアップロード", type="pdf")
if uploaded_file:
    # ファイル名（uuidでもOK、ここでは元ファイル名のまま例示）
    blob_name = f"uploads/{uploaded_file.name}"
    upload_to_gcs(uploaded_file, GCS_BUCKET_NAME, blob_name)
    st.success(f"GCSにアップロード完了: {blob_name}")
