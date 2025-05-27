from google.cloud import storage

def upload_pdf_to_gcs(local_pdf_path, gcs_bucket_name, gcs_blob_name):
    # ストレージクライアントを初期化（Cloud Run等なら認証自動）
    client = storage.Client()
    bucket = client.bucket(gcs_bucket_name)
    blob = bucket.blob(gcs_blob_name)

    # PDFファイルをアップロード
    blob.upload_from_filename(local_pdf_path)
    print(f"✅ アップロード完了: gs://{gcs_bucket_name}/{gcs_blob_name}")

if __name__ == "__main__":
    # --- 設定（環境変数やconfigから読むのがベスト）
    local_pdf_path = "test.pdf"  # ローカルのアップロード対象PDF
    gcs_bucket_name = "run-sources-rag-cloud-project-asia-northeast1"  # ←ここに自分のバケット名
    gcs_blob_name = "uploads/test.pdf"  # バケット内のパス（フォルダ風でOK）

    upload_pdf_to_gcs(local_pdf_path, gcs_bucket_name, gcs_blob_name)
