from rag.ingested_text import ingest_pdf_to_vectorstore
from fastapi import APIRouter, UploadFile, File, HTTPException
from google.cloud import storage
import uuid
import tempfile
import os
import logging

router = APIRouter()

logger = logging.getLogger(__name__)

GCS_BUCKET_NAME = os.environ.get("GCS_BUCKET_NAME")
if not GCS_BUCKET_NAME:
    logger.warning("GCS_BUCKET_NAME 環境変数が未設定です。ローカルストレージモードで動作します。")

def upload_file_to_gcs(file: UploadFile, dest_filename: str) -> str:
    """GCSにファイルをアップロード"""
    if not GCS_BUCKET_NAME:
        # GCSが設定されていない場合はローカルに保存
        local_path = f"uploads/{dest_filename}"
        os.makedirs("uploads", exist_ok=True)
        with open(local_path, "wb") as f:
            f.write(file.file.read())
        return local_path
    
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
    """GCSからローカルにファイルをダウンロード"""
    if not gs_path.startswith("gs://"):
        # ローカルファイルの場合はそのまま返す
        return gs_path
    
    assert gs_path.startswith("gs://")
    bucket_name, blob_name = gs_path[5:].split("/", 1)
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.download_to_filename(local_path)
    return local_path

@router.post("/ingest", summary="PDFファイルのアップロードとベクトル化")
async def ingest(file: UploadFile = File(...)):
    """
    PDFファイルをアップロードしてベクトル化する
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="PDFファイルのみ対応です。")

    ext = os.path.splitext(file.filename)[1]
    unique_filename = f"{uuid.uuid4().hex}{ext}"

    # 一時ファイルに保存
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        # GCSにアップロード（設定されている場合）
        gcs_path = None
        if GCS_BUCKET_NAME:
            try:
                # ファイルポインタをリセット
                file.file.seek(0)
                gcs_path = upload_file_to_gcs(file, unique_filename)
                logger.info(f"GCSアップロード成功: {gcs_path}")
            except Exception as e:
                logger.error(f"GCSアップロード失敗: {e}")
                # GCSアップロードが失敗してもベクトル化は続行

        # ベクトル化処理
        added_docs = ingest_pdf_to_vectorstore(tmp_path)
        
        # 成功レスポンス
        return {
            "filename": file.filename,
            "gcs_path": gcs_path or "ローカルストレージ",
            "added_docs": added_docs,
            "message": "アップロード＆ベクトル化完了！"
        }
        
    except Exception as e:
        logger.error(f"ベクトル化処理エラー: {e}")
        raise HTTPException(status_code=500, detail=f"ベクトル化処理失敗: {str(e)}")
    finally:
        # 一時ファイルを削除
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

# ===== 既存フロントエンド互換用エンドポイント =====
@router.post("/upload_pdf", summary="既存フロントエンド互換")
async def upload_pdf_compat(file: UploadFile = File(...)):
    """
    既存フロントエンドとの互換用エンドポイント
    """
    return await ingest(file)