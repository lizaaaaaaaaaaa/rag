# api/routers/debug_rag.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import os
import tempfile
import logging

router = APIRouter()
log = logging.getLogger("fix-rag")

# 既存のリロード関数があればそれを最優先で使う
_reload_fn = None
try:
    # 例: rag/fast_rag_chain.py にある reload_vectorstore を想定
    from rag.fast_rag_chain import reload_vectorstore as _reload_fn   # 引数名は後で吸収
except Exception:
    try:
        # 例: rag/init_vectorstore.py にある load_vectorstore を想定
        from rag.init_vectorstore import load_vectorstore as _reload_fn
    except Exception:
        _reload_fn = None

# RAGホルダー（VECTORSTOREやチェーンを持っている可能性のあるモジュール）
_HOLDER = None
try:
    import rag.fast_rag_chain as _HOLDER
except Exception:
    try:
        import services.rag_chain as _HOLDER
    except Exception:
        _HOLDER = None


# gcs_utils の “安全な” import（プロジェクト内の配置ゆれに対応）
_download_blob = None
try:
    from utils.gcs_utils import download_blob as _download_blob
except Exception:
    try:
        from utils.gcs_utils import download_blob as _download_blob  # ← ここが今回の修正要
    except Exception:
        try:
            from gcs_utils import download_blob as _download_blob
        except Exception:
            _download_blob = None


class FixRagResult(BaseModel):
    status: str
    bucket: str | None = None
    vector_prefix: str | None = None
    used: str


def _call_reload_fn_safely(bucket: str, prefix: str) -> bool:
    """
    _reload_fn の引数名差異に耐性を持たせて呼び出す。
    True を返したら成功扱い。
    """
    if not _reload_fn:
        return False
    try:
        # 代表的な呼び方を順に試す
        try:
            _reload_fn(bucket=bucket, prefix=prefix)
            return True
        except TypeError:
            pass
        try:
            _reload_fn(gcs_bucket=bucket, vector_prefix=prefix)
            return True
        except TypeError:
            pass
        try:
            _reload_fn()  # 引数無し版
            return True
        except TypeError:
            pass
    except Exception as e:
        log.exception("existing reload failed: %s", e)
    return False


@router.post("/debug/fix-rag", response_model=FixRagResult, tags=["debug"])
def fix_rag_reload():
    """
    Cloud Storage 上の FAISS を再読込して RAG を即時反映させるデバッグ用エンドポイント。
    1) 既存のリロード関数（あれば）を優先
    2) 失敗したら GCS から index.faiss / index.pkl を直ダウンロードして FAISS を復元
    """
    bucket = os.getenv("GCS_BUCKET_NAME", "").strip()
    # VECTORSTORE のプレフィックス（なければ既定）
    prefix = (
        os.getenv("VECTORSTORE_PREFIX", None)
        or os.getenv("GCS_VECTORSTORE_PREFIX", None)
        or "vectorstore/"
    ).strip()

    if not bucket:
        raise HTTPException(status_code=500, detail="GCS_BUCKET_NAME is empty")

    # 1) 既存のローダーがあればそれを使う
    if _call_reload_fn_safely(bucket=bucket, prefix=prefix):
        return FixRagResult(
            status="reloaded", bucket=bucket, vector_prefix=prefix, used="existing-loader"
        )

    # 2) フォールバック：GCS から FAISS を直ロード
    try:
        # embeddings は既存の get_embeddings があれば流用
        embeddings = None
        try:
            from rag.fast_rag_chain import get_embeddings
            embeddings = get_embeddings()
        except Exception:
            pass

        if embeddings is None:
            # 最低限の多言語E5-smallを直接用意（プロジェクトに合わせて調整可）
            from sentence_transformers import SentenceTransformer
            from langchain.embeddings.base import Embeddings

            class _SBert(Embeddings):
                def __init__(self):
                    self.m = SentenceTransformer("intfloat/multilingual-e5-small")

                def embed_query(self, t):
                    return self.m.encode(t).tolist()

                def embed_documents(self, arr):
                    return [self.m.encode(t).tolist() for t in arr]

            embeddings = _SBert()

        tmpdir = tempfile.mkdtemp(prefix="vs-")
        idx_path = os.path.join(tmpdir, "index.faiss")
        pkl_path = os.path.join(tmpdir, "index.pkl")

        if _download_blob is None:
            raise RuntimeError("download_blob util not found (utils.gcs_utils/api.utils.gcs_utils)")

        # GCS から FAISS を取得
        _download_blob(bucket, f"{prefix}index.faiss", idx_path)
        _download_blob(bucket, f"{prefix}index.pkl", pkl_path)

        # FAISS 復元
        from langchain_community.vectorstores import FAISS as LCFAISS

        vectorstore = LCFAISS.load_local(
            tmpdir,
            embeddings,
            index_name="index",
            allow_dangerous_deserialization=True,
        )

        # グローバルに保持している想定の場所へ差し替え
        if _HOLDER and hasattr(_HOLDER, "VECTORSTORE"):
            setattr(_HOLDER, "VECTORSTORE", vectorstore)
            # 再構築系の関数があれば1つ呼ぶ
            for name in ("rebuild_rag_chain", "build_chain", "init_chain"):
                if hasattr(_HOLDER, name):
                    try:
                        getattr(_HOLDER, name)()
                        break
                    except Exception:
                        # ここは致命ではないので握りつぶす
                        pass

        return FixRagResult(
            status="reloaded", bucket=bucket, vector_prefix=prefix, used="fallback-loader"
        )

    except Exception as e:
        log.exception("fallback reload failed: %s", e)
        raise HTTPException(status_code=500, detail=f"fix-rag error: {e}")
