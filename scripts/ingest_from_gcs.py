# -*- coding: utf-8 -*-
"""
GCSに置いたPDF（例: uploads/ と uploads/admin/）を一括取り込みし、
（任意で）出来上がった FAISS index を GCS にアップロード、
さらに（存在すれば）ランタイムのベクトルストアを即時リロードします。

環境変数:
- GCS_BUCKET_NAME            : 必須 例) run-sources-rag-cloud-project-asia-northeast1
- GCS_UPLOADS_PREFIXES       : 必須 例) "uploads/admin/20251005,uploads/admin/20251006"
- VECTOR_DIR                 : 既定 "rag/vectorstore"
- INDEX_NAME                 : 既定 "index"
- UPLOAD_UPDATED_VECTORSTORE_TO_GCS : "true" でアップロード
"""

from __future__ import annotations
import os
import sys
import pathlib
import traceback
from typing import Iterable, Tuple, Optional

# ---- プロジェクトルートを import パスへ（ローカル実行安定化）----
ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ---- 取り込み関数の解決（実態に合わせて多段フォールバック）----
_ingest_func = None
_errors = []

def _try_import():
    global _ingest_func
    candidates = [
        ("api.services.ingest_service", "ingest_pdf_to_vectorstore_entry"),
        ("services.ingest_service", "ingest_pdf_to_vectorstore_entry"),
        ("rag.ingest", "ingest_pdf_to_vectorstore_entry"),
        ("ingest_service", "ingest_pdf_to_vectorstore_entry"),
        ("ingest", "ingest_pdf_to_vectorstore_entry"),
    ]
    for mod, attr in candidates:
        try:
            m = __import__(mod, fromlist=[attr])
            _ingest_func = getattr(m, attr)
            print(f"[import] {mod}.{attr} OK")
            return
        except Exception as e:
            _errors.append(f"{mod}.{attr}: {e}")
    raise ImportError("ingest_pdf_to_vectorstore_entry が見つかりません:\n  - " + "\n  - ".join(_errors))

_try_import()

# ---- refresh_vectorstore（あれば使う）----
try:
    from rag.fast_rag_chain import refresh_vectorstore  # type: ignore
except Exception:
    print("[warn] rag.fast_rag_chain not found; refresh will be skipped")
    refresh_vectorstore = None  # type: ignore

# ---- GCS client ----
from google.cloud import storage  # type: ignore

VECTOR_DIR = os.getenv("VECTOR_DIR", "rag/vectorstore")
INDEX_NAME = os.getenv("INDEX_NAME", "index")
UPLOAD_UPDATED_VECTORSTORE_TO_GCS = os.getenv("UPLOAD_UPDATED_VECTORSTORE_TO_GCS", "false").lower() == "true"

def _iter_prefixes(raw: str) -> Iterable[str]:
    for p in (raw or "").split(","):
        p = p.strip()
        if p:
            if not p.endswith("/"):
                p += "/"
            yield p

def _list_objects(bucket: storage.Bucket, prefix: str) -> Iterable[storage.Blob]:
    return bucket.list_blobs(prefix=prefix)

def _upload_vectorstore_to_gcs_if_enabled(bucket: storage.Bucket) -> None:
    if not UPLOAD_UPDATED_VECTORSTORE_TO_GCS:
        print("[upload] skip (UPLOAD_UPDATED_VECTORSTORE_TO_GCS=false)")
        return
    local_faiss = pathlib.Path(VECTOR_DIR) / f"{INDEX_NAME}.faiss"
    local_pkl = pathlib.Path(VECTOR_DIR) / f"{INDEX_NAME}.pkl"
    if not local_faiss.exists() or not local_pkl.exists():
        print(f"[upload] index files not found: {local_faiss}, {local_pkl}")
        return

    def _up(local: pathlib.Path):
        blob = bucket.blob(f"vectorstore/{local.name}")
        blob.upload_from_filename(str(local))
        print(f"[upload] Uploaded to gs://{bucket.name}/vectorstore/{local.name}")

    _up(local_faiss)
    _up(local_pkl)

def main():
    bucket_name = os.environ.get("GCS_BUCKET_NAME")
    prefixes_raw = os.environ.get("GCS_UPLOADS_PREFIXES")
    if not bucket_name:
        raise SystemExit("GCS_BUCKET_NAME is required")
    if not prefixes_raw:
        raise SystemExit("GCS_UPLOADS_PREFIXES is required (comma-separated)")

    client = storage.Client()
    bucket = client.bucket(bucket_name)

    total_files = 0
    success = 0
    failed = 0

    for prefix in _iter_prefixes(prefixes_raw):
        print(f"[scan] gs://{bucket_name}/{prefix} …")
        blobs = list(_list_objects(bucket, prefix))
        if not blobs:
            print(f"[scan] (no files) {prefix}")
            continue

        for b in blobs:
            if not b.name.lower().endswith(".pdf"):
                continue
            total_files += 1
            original_filename = os.path.basename(b.name)
            gcs_path = f"gs://{bucket_name}/{b.name}"

            os.environ["INGEST_GCS_BUCKET"] = bucket_name
            os.environ["INGEST_GCS_BLOB_NAME"] = b.name
            os.environ["INGEST_ORIGINAL_FILENAME"] = original_filename

            try:
                print(f"[ingest] {gcs_path}")
                _ingest_func(gcs_path)  # ← ingest_pdf_to_vectorstore_entry(str path)
                success += 1
            except Exception as e:
                failed += 1
                print(f"[error] ingest failed: {gcs_path}: {e}")
                traceback.print_exc()

    print(f"[summary] total={total_files} success={success} failed={failed}")

    # （任意）更新版ベクトルストアをGCSへ反映
    _upload_vectorstore_to_gcs_if_enabled(bucket)

    # ランタイムへ即時反映（FAST 実装があれば）
    if callable(refresh_vectorstore):
        try:
            refresh_vectorstore(force=True)
            print("[reload] vectorstore reloaded (force=true)")
        except Exception as e:
            print(f"[warn] refresh failed: {e}")

if __name__ == "__main__":
    main()