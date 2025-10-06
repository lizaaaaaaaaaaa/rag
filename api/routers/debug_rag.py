# api/routers/debug_rag.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import os, tempfile, logging

router = APIRouter()
log = logging.getLogger("fix-rag")

# 既存ローダーがあれば優先して使う（あなたの実装に合わせて調整可）
_reload_fn = None
try:
    from rag.fast_rag_chain import reload_vectorstore as _reload_fn  # あれば使う
except Exception:
    try:
        from rag.init_vectorstore import load_vectorstore as _reload_fn
    except Exception:
        _reload_fn = None

_HOLDER = None
try:
    import rag.fast_rag_chain as _HOLDER  # VECTORSTORE を保持している想定
except Exception:
    try:
        import services.rag_chain as _HOLDER
    except Exception:
        _HOLDER = None


class FixRagResult(BaseModel):
    status: str
    bucket: str | None = None
    vector_prefix: str | None = None
    used: str


@router.post("/debug/fix-rag", response_model=FixRagResult, tags=["debug"])
def fix_rag_reload():
    bucket = os.getenv("GCS_BUCKET_NAME", "").strip()
    prefix = os.getenv("VECTORSTORE_PREFIX", "vectorstore/").strip()
    if not bucket:
        raise HTTPException(status_code=500, detail="GCS_BUCKET_NAME is empty")

    # 1) 既存のローダーがあればそれを使う
    if _reload_fn:
        try:
            _reload_fn(bucket=bucket, prefix=prefix)  # ← 引数名は実装に合わせてください
            return FixRagResult(status="reloaded", bucket=bucket, vector_prefix=prefix, used="existing-loader")
        except Exception as e:
            log.exception("existing reload failed: %s", e)

    # 2) フォールバック：GCS からFAISSを直ロード
    try:
        import os
        from langchain_community.vectorstores import FAISS as LCFAISS
        # 既存の embeddings 取得関数があれば利用
        embeddings = None
        try:
            from rag.fast_rag_chain import get_embeddings
            embeddings = get_embeddings()
        except Exception:
            pass
        if embeddings is None:
            from sentence_transformers import SentenceTransformer
            from langchain.embeddings.base import Embeddings
            class _SBert(Embeddings):
                def __init__(self):
                    self.m = SentenceTransformer("intfloat/multilingual-e5-small")
                def embed_query(self, t): return self.m.encode(t).tolist()
                def embed_documents(self, arr): return [self.m.encode(t).tolist() for t in arr]
            embeddings = _SBert()

        tmpdir = tempfile.mkdtemp(prefix="vs-")
        idx_path = os.path.join(tmpdir, "index.faiss")
        pkl_path = os.path.join(tmpdir, "index.pkl")

        # ダウンロード（既存の util を優先）
        downloaded = False
        try:
            from utils.gcs_utils import download_blob
            downloaded = True
        except Exception:
            try:
                from gcs_utils import download_blob
                downloaded = True
            except Exception:
                downloaded = False
        if not downloaded:
            raise RuntimeError("no download_blob util")

        download_blob(bucket, f"{prefix}index.faiss", idx_path)
        download_blob(bucket, f"{prefix}index.pkl", pkl_path)

        vectorstore = LCFAISS.load_local(
            tmpdir, embeddings, index_name="index", allow_dangerous_deserialization=True
        )
        if _HOLDER and hasattr(_HOLDER, "VECTORSTORE"):
            setattr(_HOLDER, "VECTORSTORE", vectorstore)
            # 再構築関数があれば呼ぶ
            for name in ("rebuild_rag_chain", "build_chain", "init_chain"):
                if hasattr(_HOLDER, name):
                    try:
                        getattr(_HOLDER, name)()
                        break
                    except Exception:
                        pass

        return FixRagResult(status="reloaded", bucket=bucket, vector_prefix=prefix, used="fallback-loader")
    except Exception as e:
        log.exception("fallback reload failed: %s", e)
        raise HTTPException(status_code=500, detail=f"fix-rag error: {e}")
