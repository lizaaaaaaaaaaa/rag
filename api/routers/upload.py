from rag.ingested_text import ingest_pdf_to_vectorstore
from fastapi import APIRouter, UploadFile, File, HTTPException
from google.cloud import storage
import uuid
import tempfile
import os

router = APIRouter()

# GCSバケット名（自分のものに変更してね）
GCS_BUCKET_NAME = "run-sources-rag-cloud-project-asia-northeast1"  # ←ここを自分のバケット名に！

def upload_file_to_gcs(file: UploadFile, dest_filename: str) -> str:
    """
    ファイルを一時保存し、GCSにアップロード。GCSのgs://パスを返す。
    """
    # 一時ファイルとして保存
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(file.file.read())
        tmp_path = tmp.name

    try:
        client = storage.Client()
        bucket = client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(dest_filename)
        blob.upload_from_filename(tmp_path)
    finally:
        # 一時ファイルは必ず削除
        os.remove(tmp_path)

    return f"gs://{GCS_BUCKET_NAME}/{dest_filename}"

@router.post("/upload_pdf", summary="PDFファイルのアップロード")
async def upload_pdf(file: UploadFile = File(...)):
    # PDF拡張子チェック
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="PDFファイルのみ対応です。")

    # ファイル名をUUIDでユニーク化（日本語名・重複対策）
    ext = os.path.splitext(file.filename)[1]
    unique_filename = f"{uuid.uuid4().hex}{ext}"

    # GCSにアップロード
    try:
        gcs_path = upload_file_to_gcs(file, unique_filename)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"GCSアップロード失敗: {e}")

    # ベクトルストアに取り込み（GCS対応バージョン必須）
    try:
        ingest_pdf_to_vectorstore(gcs_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ベクトル化処理失敗: {e}")

    return {
        "filename": file.filename,
        "gcs_path": gcs_path,
        "message": "アップロード＆ベクトル化完了！"
    }
