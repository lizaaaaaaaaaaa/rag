# -*- coding: utf-8 -*-
"""
GCSに置いたPDF（例: uploads/ と uploads/admin/）を既存の取り込みロジックで一括取り込みし、
必要に応じてFAISSをリロード＆（任意で）最新版のindexをGCSへ反映するスクリプト。

本スクリプトは ingest_service.ingest_pdf_to_vectorstore_entry（または同等）へ委譲します。
さらに、取り込み直前に以下の環境変数を設定して、ingested_text.py 側で
メタデータ（original_filename / gcs_path / page）を確実に付与できるようにします：

- INGEST_GCS_BUCKET
- INGEST_GCS_BLOB_NAME
- INGEST_ORIGINAL_FILENAME

環境変数:
- GCS_BUCKET_NAME  : 必須 例) run-sources-rag-cloud-project-asia-northeast1
- GCS_UPLOADS_PREFIXES : 取り込み対象プレフィックスのカンマ区切り
                         例) "uploads/,uploads/admin/" （末尾スラッシュ可）
- VECTOR_DIR       : ベクトルストアのローカルパス (既定: rag/vectorstore)
- INDEX_NAME       : インデックス名 (既定: index)
- UPLOAD_UPDATED_VECTORSTORE_TO_GCS : true なら取り込み後にGCSへ最新版のindexをアップロード（任意）

実行:
    $ export GCS_BUCKET_NAME=run-sources-rag-cloud-project-asia-northeast1
    $ export GCS_UPLOADS_PREFIXES="uploads/,uploads/admin/"
    $ python scripts/ingest_from_gcs.py

Cloud Run Job にもそのまま載せられます。
"""
from __future__ import annotations

import os
import sys
from tempfile import NamedTemporaryFile
from typing import Iterable, List

# --- ローカル import 解決（配置差異を吸収） ---
try:
    from ingest_service import ingest_pdf_to_vectorstore_entry as ingest_one  # type: ignore
except Exception:
    try:
        from services.ingest_service import ingest_pdf_to_vectorstore_entry as ingest_one  # type: ignore
    except Exception:
        from ingest import ingest_pdf_to_vectorstore_entry as ingest_one  # type: ignore

try:
    from rag.fast_rag_chain import refresh_vectorstore  # type: ignore
except Exception:
    # 見つからない環境ではスキップ
    print("[warn] rag.fast_rag_chain not found; refresh will be skipped")
    refresh_vectorstore = None  # type: ignore

# GCSユーティリティ
from google.cloud import storage  # type: ignore

VECTOR_DIR = os.getenv("VECTOR_DIR", "rag/vectorstore")
INDEX_NAME = os.getenv("INDEX_NAME", "index")
UPLOAD_UPDATED_VECTORSTORE_TO_GCS = os.getenv("UPLOAD_UPDATED_VECTORSTORE_TO_GCS", "false").lower() == "true"


def _iter_prefixes() -> List[str]:
    raw = os.getenv("GCS_UPLOADS_PREFIXES", "uploads/")
    ps = [p.strip() for p in raw.split(",") if p.strip()]
    # 末尾スラッシュを保証
    return [p if p.endswith("/") else p + "/" for p in ps]


def _is_pdf_name(name: str) -> bool:
    return name.lower().endswith(".pdf")


def _upload_vectorstore_to_gcs_if_enabled(bucket: str) -> None:
    if not UPLOAD_UPDATED_VECTORSTORE_TO_GCS:
        return
    try:
        from ingested_text import upload_vectorstore_to_gcs  # type: ignore
        upload_vectorstore_to_gcs(VECTOR_DIR)
        print(f"[sync] uploaded local vectorstore to gs://{bucket}/vectorstore/")
    except Exception as e:
        print(f"[warn] upload_vectorstore_to_gcs skipped: {e}")


def ingest_from_gcs(bucket_name: str, prefixes: Iterable[str]) -> int:
    client = storage.Client()
    bucket = client.bucket(bucket_name)

    total = 0
    for prefix in prefixes:
        print(f"[scan] gs://{bucket_name}/{prefix} …")
        for blob in bucket.list_blobs(prefix=prefix):
            if not _is_pdf_name(blob.name):
                continue

            # 一時ファイルに落としてから既存ロジックに委譲
            with NamedTemporaryFile(suffix=".pdf") as tmp:
                blob.download_to_filename(tmp.name)
                try:
                    # --- ここが今回の追加: 取り込み先に GCS メタ情報を渡す ---
                    # ingested_text.py が original_filename / gcs_path / page を補完できるようにする
                    os.environ["INGEST_GCS_BUCKET"] = bucket_name
                    os.environ["INGEST_GCS_BLOB_NAME"] = blob.name
                    os.environ["INGEST_ORIGINAL_FILENAME"] = os.path.basename(blob.name)

                    ingest_one(tmp.name)
                    total += 1

                    if total % 20 == 0:
                        print(f"[progress] ingested {total} files so far…")
                except Exception as e:
                    print(f"[error] ingest failed for {blob.name}: {e}")

    return total


def main() -> None:
    bucket = os.environ["GCS_BUCKET_NAME"]
    prefixes = _iter_prefixes()

    print(f"[start] ingest from gs://{bucket}/ {' ,'.join(prefixes)}")
    n = ingest_from_gcs(bucket, prefixes)
    print(f"[done] ingested {n} pdf(s)")

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
