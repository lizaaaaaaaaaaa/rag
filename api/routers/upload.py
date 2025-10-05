# -*- coding: utf-8 -*-
"""
upload.py — 完全修正版（最小影響・即時反映 任意化）

変更方針（最小差分）:
- 既存の I/F / バリデーション / GCS 保存の挙動は維持
- 取り込み直後の RAG リロードを **環境変数で任意化**（既定: 有効）
- 失敗時でも既存動作を壊さないように try/except で保護

ENV:
- ENFORCE_CONSENT_UPLOAD (default: true)
- GCS_BUCKET_NAME ("" なら未使用)
- REFRESH_AFTER_INGEST (default: true)
- RAG_RELOAD_COOLDOWN_SEC (fast_rag_chain 側で使用)
"""
from __future__ import annotations

import os, re, uuid, shutil, datetime as dt
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Header, HTTPException
from fastapi.responses import JSONResponse

# 取り込み関数の所在ゆれ対策（既存）
from ..services.ingest_service import (
    ingest_pdf_to_vectorstore_entry as ingest_pdf_to_vectorstore,
)

router = APIRouter(prefix="/upload", tags=["upload"])


def _boolenv(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    return default if v is None else str(v).lower() in ("1", "true", "yes", "on")


GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "").strip()
ENFORCE_CONSENT_UPLOAD = _boolenv("ENFORCE_CONSENT_UPLOAD", True)  # 本番は True 推奨
REFRESH_AFTER_INGEST = _boolenv("REFRESH_AFTER_INGEST", True)     # ★追加: 取り込み直後の即時反映


def _safe(name: str) -> str:
    return re.sub(r"[^\w\.\-]+", "_", name)[:128]


def _save_to_gcs(local_path: Path, object_name: str, *, metadata: Optional[dict] = None) -> str:
    from google.cloud import storage
    client = storage.Client()
    bucket = client.bucket(GCS_BUCKET_NAME)
    blob = bucket.blob(object_name)
    if metadata:
        blob.metadata = metadata
    blob.upload_from_filename(str(local_path), content_type="application/pdf")
    return f"gs://{GCS_BUCKET_NAME}/{object_name}"


# 任意: RAGリロード関数（存在しない環境でも壊さない）
try:
    from ..rag.fast_rag_chain import refresh_vectorstore as _refresh_vectorstore  # type: ignore
except Exception:
    _refresh_vectorstore = None  # type: ignore


@router.post("/ingest", summary="PDFのアップロードと取り込み（Consentはアップロードのみ強制）")
async def ingest(
    file: UploadFile = File(...),  # File(...) に注意
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_consent_token: Optional[str] = Header(None, alias="X-Consent-Token"),
    x_platform: Optional[str] = Header("web", alias="X-Platform"),
):
    # ---- Consent（アップロード専用）----
    if ENFORCE_CONSENT_UPLOAD and not (x_user_id or authorization or x_consent_token):
        raise HTTPException(status_code=403, detail="consent_required: unidentified_user")

    # ---- バリデーション ----
    if not file or not file.filename:
        raise HTTPException(status_code=400, detail="no file")
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="only pdf is allowed")

    # ---- 一時保存（Cloud Run は /tmp が書込可）----
    tmp_dir = Path("/tmp/uploads"); tmp_dir.mkdir(parents=True, exist_ok=True)
    safe_name = _safe(file.filename)
    tmp_path = tmp_dir / f"{uuid.uuid4().hex}_{safe_name}"
    with tmp_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    # ---- GCS へ保存（設定があれば）----
    gcs_path = None
    if GCS_BUCKET_NAME:
        today = dt.datetime.utcnow().strftime("%Y%m%d")
        user_tag = (x_user_id or "anonymous").lower()
        object_name = f"uploads/{user_tag}/{today}/{uuid.uuid4().hex}_{safe_name}"
        try:
            gcs_path = _save_to_gcs(
                tmp_path, object_name,
                metadata={
                    "uploaded_by": user_tag,
                    "platform": x_platform or "web",
                    "consent": "yes" if (x_user_id or authorization or x_consent_token) else "no",
                    "source": "streamlit",
                },
            )
        except Exception as e:
            return JSONResponse(status_code=500, content={"detail": f"gcs_upload_failed: {type(e).__name__}: {e}"})

    # ---- ベクトル化 ----
    try:
        added = ingest_pdf_to_vectorstore(str(tmp_path))
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": f"ingest_failed: {type(e).__name__}: {e}"})

    # ---- 取り込み直後の即時反映（環境で任意）----
    rag_reloaded = False
    if REFRESH_AFTER_INGEST and _refresh_vectorstore is not None:
        try:
            _refresh_vectorstore()  # クールダウンは関数側で処理
            rag_reloaded = True
        except Exception:
            # 失敗しても取り込み自体は成功として扱う
            rag_reloaded = False

    return {
        "filename": safe_name,
        "gcs_path": gcs_path,
        "added_docs": added,
        "rag_reloaded": rag_reloaded,  # ★追加: 即時反映の成否
        "message": "ingest_ok",
    }


# 旧クライアント互換
@router.post("/upload_pdf", summary="後方互換：/upload/ingest を呼び出します")
async def upload_pdf_compat(
    file: UploadFile = File(...),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_consent_token: Optional[str] = Header(None, alias="X-Consent-Token"),
    x_platform: Optional[str] = Header("web", alias="X-Platform"),
):
    return await ingest(
        file=file,
        x_user_id=x_user_id,
        authorization=authorization,
        x_consent_token=x_consent_token,
        x_platform=x_platform,
    )