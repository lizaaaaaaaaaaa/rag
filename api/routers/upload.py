# upload.py
import os
import re
import uuid
import shutil
import datetime as dt
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Header, HTTPException
from fastapi.responses import JSONResponse

# 既存の ingest 関数をインポート（あなたの既存構成に合わせて）
# 例: from ingested_text import ingest_pdf_to_vectorstore
from rag. ingested_text import ingest_pdf_to_vectorstore  # ← 実プロジェクトに合わせて

router = APIRouter(prefix="/upload", tags=["upload"])

def _boolenv(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return str(v).lower() in ("1", "true", "yes", "on")

GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME")
CONSENT_ENFORCE = _boolenv("CONSENT_ENFORCE", False)  # Webを通すなら False を推奨

# --- GCS helper ---
def _save_to_gcs(local_path: Path, object_name: str, *, metadata: Optional[dict] = None) -> str:
    """
    /tmp に保存したファイルを GCS にアップロードして gs:// パスを返す
    """
    from google.cloud import storage
    client = storage.Client()
    bucket = client.bucket(GCS_BUCKET_NAME)
    blob = bucket.blob(object_name)
    if metadata:
        blob.metadata = metadata
    blob.upload_from_filename(str(local_path), content_type="application/pdf")
    return f"gs://{GCS_BUCKET_NAME}/{object_name}"

def _safe_filename(name: str) -> str:
    # ASCII以外/危険文字を置換
    base = re.sub(r"[^\w\.\-]+", "_", name)
    return base[:128]

@router.post("/ingest")
async def ingest(
    file: UploadFile = File(...),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_platform: Optional[str] = Header("web", alias="X-Platform"),
):
    # --- Consent check ---
    if CONSENT_ENFORCE and not x_user_id:
        raise HTTPException(status_code=403, detail="consent_required: unidentified_user")

    # --- 型/拡張子チェック（最低限） ---
    if not file or not file.filename:
        raise HTTPException(status_code=400, detail="no file")
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="only pdf is allowed")

    # --- 一時保存（/tmp） ---
    tmp_dir = Path("/tmp/uploads")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    safe_name = _safe_filename(file.filename)
    tmp_path = tmp_dir / f"{uuid.uuid4().hex}_{safe_name}"
    with tmp_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    # --- GCS へ保存 or ローカル保持 ---
    gcs_path = None
    if GCS_BUCKET_NAME:
        today = dt.datetime.utcnow().strftime("%Y%m%d")
        user = (x_user_id or "anonymous").lower()
        object_name = f"uploads/{user}/{today}/{uuid.uuid4().hex}_{safe_name}"

        try:
            gcs_path = _save_to_gcs(
                tmp_path, object_name,
                metadata={"uploaded_by": user, "platform": x_platform or "web", "source": "streamlit"}
            )
        except Exception as e:
            # GCS失敗時のフォールバック（本番では失敗させた方がよければ raise でもOK）
            return JSONResponse(
                status_code=500,
                content={"detail": f"gcs_upload_failed: {type(e).__name__}: {e}"}
            )

    # --- ベクトル化（ローカルの /tmp パスを渡す） ---
    try:
        added_docs = ingest_pdf_to_vectorstore(str(tmp_path))
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": f"ingest_failed: {type(e).__name__}: {e}"})

    return {
        "filename": safe_name,
        "gcs_path": gcs_path,
        "added_docs": added_docs,
        "message": "ingest_ok",
    }

@router.post("/upload_pdf")
async def upload_pdf_compat(
    file: UploadFile = File(...),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_platform: Optional[str] = Header("web", alias="X-Platform"),
):
    # 後方互換のラッパー
    return await ingest(file=file, x_user_id=x_user_id, x_platform=x_platform)
