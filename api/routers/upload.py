from rag.ingest import ingest_pdf_to_vectorstore
from fastapi import APIRouter, UploadFile, File, HTTPException
from google.cloud import storage
import uuid
import tempfile
import os

router = APIRouter()

GCS_BUCKET_NAME = os.environ.get("GCS_BUCKET_NAME")
if not GCS_BUCKET_NAME:
    raise RuntimeError("GCS_BUCKET_NAME 環境変数が未設定です")

def upload_file_to_gcs(file: UploadFile, dest_filename: str) -> str:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(file.file.read())
        tmp_path = tmp.name

    try:
        client = storage.Client()
        bucket = client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(dest_filename)
        blob.upload_from_filename(tmp_path)
    finally:
        os.remove(tmp_path)

    return f"gs://{GCS_BUCKET_NAME}/{dest_filename}"

def download_gcs_to_local(gs_path: str, local_path: str):
    assert gs_path.startswith("gs://")
    bucket_name, blob_name = gs_path[5:].split("/", 1)
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.download_to_filename(local_path)
    return local_path

@router.post("/ingest", summary="PDFファイルのアップロードとベクトル化")
async def ingest(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="PDFファイルのみ対応です。")

    ext = os.path.splitext(file.filename)[1]
    unique_filename = f"{uuid.uuid4().hex}{ext}"

    # GCSにアップロード
    try:
        gcs_path = upload_file_to_gcs(file, unique_filename)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"GCSアップロード失敗: {e}")

    # GCSから一時ローカルへダウンロードしてベクトル化
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp_path = tmp.name
        download_gcs_to_local(gcs_path, tmp_path)
        added = ingest_pdf_to_vectorstore(tmp_path)
        os.remove(tmp_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ベクトル化処理失敗: {e}")

    return {
        "filename": file.filename,
        "gcs_path": gcs_path,
        "added_docs": added,
        "message": "アップロード＆ベクトル化完了！"
    }
