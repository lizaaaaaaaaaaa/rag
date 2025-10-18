# -*- coding: utf-8 -*-
# scripts/ingest_faq_csv.py
# FAQ(CSV)をGCSから取り込み→FAISSへ反映
# - 取り込み後に（任意で）GCSへベクトルストアをアップロード
# - さらに、ランタイムのRAGベクトルストアを即時リロード（可能な場合）

from __future__ import annotations

import os
import csv
import pathlib
import logging
from typing import List, TYPE_CHECKING

from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain.docstore.document import Document

# ========= ロギング =========
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("ingest_faq_csv")

# ========= 設定 =========
VECTOR_DIR = os.getenv("VECTOR_DIR", "/tmp/rag/vectorstore")
# 互換: VECTOR_INDEX_NAME が優先、無ければ INDEX_NAME、さらに無ければ "index"
INDEX_NAME = os.getenv("VECTOR_INDEX_NAME") or os.getenv("INDEX_NAME", "index")

BUCKET = os.getenv("GCS_BUCKET_NAME", "")
FAQ_OBJECT = os.getenv("FAQ_OBJECT", "faq/faq.csv")  # 例: faq/faq.csv
EMBED_MODEL = os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-small")

UPLOAD_UPDATED_VECTORSTORE_TO_GCS = os.getenv("UPLOAD_UPDATED_VECTORSTORE_TO_GCS", "false").lower() == "true"

# ========= 型ヒント（静的のみ）=========
if TYPE_CHECKING:
    from google.cloud.storage import Client as StorageClient  # noqa: F401

# ========= GCS クライアント =========
try:
    from google.cloud import storage
except Exception as e:
    storage = None  # type: ignore[assignment]
    logger.warning(f"google.cloud.storage not available: {e}")

def _require_gcs() -> "StorageClient":
    """
    実行時には google-cloud-storage を必須にし、
    型の解決は TYPE_CHECKING ブロックでのみ行う。
    """
    if storage is None:
        raise RuntimeError("google-cloud-storage is not available")
    return storage.Client()  # type: ignore[no-any-return]

# ========= RAGの即時リロード（任意）=========
def _refresh_runtime_vectorstore() -> bool:
    """
    rag.fast_rag_chain.refresh_vectorstore(force=True) を呼び出して
    ランタイムのベクトルストアを即時更新。存在しなければ無視。
    """
    try:
        # rag.fast_rag_chain を最優先パスとする
        from rag.fast_rag_chain import refresh_vectorstore  # type: ignore
        refresh_vectorstore(force=True)
        logger.info("✅ Runtime vectorstore refresh requested (force=True).")
        return True
    except Exception as e:
        logger.info(f"(optional) refresh_vectorstore not executed: {e}")
        return False

# ========= GCSへベクトルストアを同期（任意）=========
def _upload_vectorstore_to_gcs(local_dir: str) -> bool:
    """
    rag.ingested_text.upload_vectorstore_to_gcs が存在すればそれを利用し、
    無ければこの関数の実装でアップロードする。
    """
    # まず既存の実装があれば利用
    try:
        from rag.ingested_text import upload_vectorstore_to_gcs  # type: ignore
        upload_vectorstore_to_gcs(local_dir)
        logger.info("✅ Vectorstore uploaded to GCS via rag.ingested_text.upload_vectorstore_to_gcs")
        return True
    except Exception as e:
        logger.info(f"fallback upload (couldn't import rag.ingested_text.upload_vectorstore_to_gcs): {e}")

    # フォールバック実装
    if not BUCKET:
        logger.info("GCS_BUCKET_NAME not set. Skip uploading vectorstore to GCS.")
        return False
    try:
        client = _require_gcs()
        bucket = client.bucket(BUCKET)
        uploaded = False
        for fname in (f"{INDEX_NAME}.faiss", f"{INDEX_NAME}.pkl"):
            local_path = os.path.join(local_dir, fname)
            if not os.path.exists(local_path):
                continue
            blob_path = f"vectorstore/{fname}"
            blob = bucket.blob(blob_path)
            blob.upload_from_filename(local_path)
            logger.info(f"✅ Uploaded to GCS: gs://{BUCKET}/{blob_path}")
            uploaded = True
        return uploaded
    except Exception as e:
        logger.error(f"GCS upload error: {e}")
        return False

# ========= FAQ(CSV) ロード =========
def _load_faq_from_gcs() -> List[Document]:
    """
    GCSのCSVを読み込み、Q/Aを Document として返す。
    CSVは UTF-8 で、ヘッダは「質問/回答」または「question/answer」を想定。
    """
    if not BUCKET:
        raise RuntimeError("GCS_BUCKET_NAME is required")
    client = _require_gcs()

    blob = client.bucket(BUCKET).blob(FAQ_OBJECT)
    if not blob.exists():
        raise FileNotFoundError(f"FAQ CSV not found: gs://{BUCKET}/{FAQ_OBJECT}")

    data = blob.download_as_text(encoding="utf-8")
    rows = list(csv.DictReader(data.splitlines()))
    docs: List[Document] = []
    for r in rows:
        q = (r.get("質問") or r.get("question") or "").strip()
        a = (r.get("回答") or r.get("answer") or "").strip()
        if not q or not a:
            continue
        # 質問をメタに入れておくとデバッグ/評価しやすい
        docs.append(
            Document(
                page_content=f"Q: {q}\nA: {a}",
                metadata={"source": f"gs://{BUCKET}/{FAQ_OBJECT}", "type": "faq", "question": q}
            )
        )
    return docs

# ========= ベクトルストアへ反映 =========
def _save_to_vectorstore(docs: List[Document]) -> None:
    pathlib.Path(VECTOR_DIR).mkdir(parents=True, exist_ok=True)
    emb = HuggingFaceEmbeddings(model_name=EMBED_MODEL)

    index_faiss = os.path.join(VECTOR_DIR, f"{INDEX_NAME}.faiss")
    index_pkl = os.path.join(VECTOR_DIR, f"{INDEX_NAME}.pkl")

    if os.path.exists(index_faiss) and os.path.exists(index_pkl):
        # 既存ベクトルストアに追記
        try:
            vs = FAISS.load_local(
                VECTOR_DIR,
                emb,
                index_name=INDEX_NAME,
                allow_dangerous_deserialization=True
            )
            vs.add_documents(docs)
            vs.save_local(VECTOR_DIR, index_name=INDEX_NAME)
            logger.info(f"✅ Appended {len(docs)} docs to existing vectorstore.")
        except Exception as e:
            logger.warning(f"Append failed ({e}), recreate vectorstore...")
            vs = FAISS.from_documents(docs, emb)
            vs.save_local(VECTOR_DIR, index_name=INDEX_NAME)
            logger.info(f"✅ Recreated vectorstore with {len(docs)} docs.")
    else:
        # 新規作成
        vs = FAISS.from_documents(docs, emb)
        vs.save_local(VECTOR_DIR, index_name=INDEX_NAME)
        logger.info(f"✅ Created new vectorstore with {len(docs)} docs.")

    logger.info(f"📦 Saved -> {VECTOR_DIR}/{INDEX_NAME}.faiss / .pkl")

# ========= main =========
def main():
    logger.info("🚚 Start ingesting FAQ CSV from GCS...")
    docs = _load_faq_from_gcs()
    if not docs:
        logger.warning("No docs found in CSV. Nothing to ingest.")
        return

    _save_to_vectorstore(docs)

    # 追加: 任意でGCSへ同期
    if UPLOAD_UPDATED_VECTORSTORE_TO_GCS:
        _upload_vectorstore_to_gcs(VECTOR_DIR)

    # 追加: ランタイムへ即反映（存在すれば）
    _refresh_runtime_vectorstore()

    logger.info("🎉 Ingest finished successfully.")

if __name__ == "__main__":
    main()