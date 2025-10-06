# api/routers/debug_rag.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import os, logging, tempfile
from typing import Optional

router = APIRouter()
log = logging.getLogger("fix-rag")

# 既存のローダー優先（あなたの実装に合わせて自動で拾う）
_reload_fn = None
try:
    # あればこちらを使う
    from rag.fast_rag_chain import reload_vectorstore as _reload_fn   # 例
except Exception:
    try:
        from rag.init_vectorstore import load_vectorstore as _reload_fn  # 例
    except Exception:
        _reload_fn = None  # フォールバックに切替

# ベクトルストア保持先（グローバル変数を持っているモジュール）
_HOLDER = None
try:
    import rag.fast_rag_chain as _HOLDER   # 例：ここに VECTORSTORE / rebuild 関数がある想定
except Exception:
    try:
        import services.rag_chain as _HOLDER
    except Exception:
        _HOLDER = None


class FixRagResult(BaseModel):
    status: str
    bucket: Optional[str] = None
    vector_prefix: Optional[str] = None
    used: str


@router.post("/debug/fix-rag", response_model=FixRagResult, tags=["debug"])
def fix_rag_reload():
    """
    GCS 上の vectorstore を読み直してアプリ内のベクトルストアを更新。
    まず既存のローダー(_reload_fn)を呼び、無ければFAISSを直接ロードするフォールバック。
    """
    bucket = os.getenv("GCS_BUCKET_NAME", "").strip()
    prefix = os.getenv("VECTORSTORE_PREFIX", "vectorstore/").strip()
    if not bucket:
        raise HTTPException(status_code=500, detail="GCS_BUCKET_NAME is empty")

    # 1) 既存ローダーがあればそれを使う（最小変更）
    if _reload_fn is not None:
        try:
            # ★必要に応じて引数名をあなたの関数シグネチャに合わせてください
            _reload_fn(bucket=bucket, prefix=prefix)
            return FixRagResult(status="reloaded", bucket=bucket, vector_prefix=prefix, used="existing-loader")
        except Exception as e:
            log.exception("existing reload function failed: %s", e)
            # フォールバックに続行

    # 2) フォールバック：GCS→/tmp にDLして FAISS を直接ロード
    try:
        tmpdir = tempfile.mkdtemp(prefix="vs-")
        idx_path = os.path.join(tmpdir, "index.faiss")
        pkl_path = os.path.join(tmpdir, "index.pkl")

        # a) ダウンロード（手元のユーティリティを優先）
        downloaded = False
        try:
            from utils.gcs_utils import download_blob  # 例：あなたのパスに合わせて
            download_blob(bucket, f"{prefix}index.faiss", idx_path)
            download_blob(bucket, f"{prefix}index.pkl", pkl_path)
            downloaded = True
        except Exception:
            try:
                from gcs_utils import download_blob
                download_blob(bucket, f"{prefix}index.faiss", idx_path)
                download_blob(bucket, f"{prefix}index.pkl", pkl_path)
                downloaded = True
            except Exception as e:
                log.exception("download failed: %s", e)

        if not downloaded:
            raise RuntimeError("failed to download vectorstore from GCS")

        # b) LangChain FAISS をロード
        from langchain_community.vectorstores import FAISS as LCFAISS
        # 既存の埋め込み取得を優先
        embeddings = None
        try:
            from rag.fast_rag_chain import get_embeddings  # あれば
            embeddings = get_embeddings()
        except Exception:
            pass

        if embeddings is None:
            # 既定の埋め込み（必要ならプロジェクトの標準に差し替え）
            from sentence_transformers import SentenceTransformer
            from langchain.embeddings.base import Embeddings
            class _SBert(Embeddings):
                def __init__(self):
                    self.model = SentenceTransformer("intfloat/multilingual-e5-small")
                def embed_query(self, t): return self.model.encode(t).tolist()
                def embed_documents(self, arr): return [self.model.encode(t).tolist() for t in arr]
            embeddings = _SBert()

        vectorstore = LCFAISS.load_local(
            tmpdir,
            embeddings,
            index_name="index",
            allow_dangerous_deserialization=True
        )
        if vectorstore is None:
            raise RuntimeError("vectorstore load returned None")

        # c) グローバル更新（あなたの保持先に合わせる）
        if _HOLDER is not None:
            if hasattr(_HOLDER, "VECTORSTORE"):
                setattr(_HOLDER, "VECTORSTORE", vectorstore)
            # チェーン再構築関数があれば呼ぶ
            for name in ("rebuild_rag_chain", "build_chain", "init_chain"):
                if hasattr(_HOLDER, name):
                    try:
                        getattr(_HOLDER, name)()
                        break
                    except Exception:
                        pass

        log.info("RAG vectorstore reloaded from gs://%s/%s", bucket, prefix)
        return FixRagResult(status="reloaded", bucket=bucket, vector_prefix=prefix, used="fallback-loader")

    except Exception as e:
        log.exception("fix-rag fallback failed: %s", e)
        raise HTTPException(status_code=500, detail=f"fix-rag error: {e}")
