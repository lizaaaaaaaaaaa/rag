# services/rag_chain.py
"""
RAGフロントドア（sources整形対応版）:
- 可能なら FAST 実装（rag.fast_rag_chain）を使用
- 失敗時は STANDARD（FAISS + RetrievalQA）にフォールバック
戻り値: (answer: str, sources: list[str])
環境変数:
  RAG_IMPL=FAST|STANDARD        # 既定: FAST
  INCLUDE_SOURCES=true|false    # true で JSON の sources を返す
  VECTOR_DIR                    # 既定: Cloud Run は /tmp/rag/vectorstore, それ以外は rag/vectorstore
  INDEX_NAME                    # 既定: index
"""

from __future__ import annotations
import os
import re
from typing import List, Tuple, Optional

# ---------------------------------------------------------
# 設定
# ---------------------------------------------------------
RAG_IMPL_FAST = os.getenv("RAG_IMPL", "FAST").upper() == "FAST"
INCLUDE_SOURCES = os.getenv("INCLUDE_SOURCES", "false").lower() == "true"

# Cloud Run 上では /tmp を既定に
if os.getenv("K_SERVICE"):
    VECTOR_DIR_DEFAULT = "/tmp/rag/vectorstore"
else:
    VECTOR_DIR_DEFAULT = "rag/vectorstore"

VECTOR_DIR = os.getenv("VECTOR_DIR", VECTOR_DIR_DEFAULT)
INDEX_NAME = os.getenv("INDEX_NAME", "index")

# ---------------------------------------------------------
# 出典ラベル整形（A 案の実装）
# ---------------------------------------------------------
def _basename(p: str) -> str:
    try:
        return os.path.basename(p or "")
    except Exception:
        return p or ""

def _format_source(md: dict) -> Optional[str]:
    """
    出典名の優先順位:
      1) original_filename
      2) basename(gcs_path)
      3) basename(source)
    さらに、page / page_number / pageIndex を (p.X) 形式で付与。
    original_filename がある場合は tmp*.pdf のような一時名は置き換える。
    """
    name = md.get("original_filename")
    gcs_path = md.get("gcs_path") or ""
    if not name and gcs_path:
        name = _basename(gcs_path)
    if not name:
        name = _basename(md.get("source", ""))

    if not name:
        return None

    # tmp*.pdf → original_filename に置き換え（original_filename がある時のみ）
    if md.get("original_filename"):
        if re.match(r"^tmp[^/\\]*\.pdf$", name, re.IGNORECASE):
            name = md["original_filename"]

    page = md.get("page")
    if page is None:
        page = md.get("page_number") or md.get("pageIndex")

    return f"{name} (p.{page})" if page is not None else name


# ---------------------------------------------------------
# FAST 実装（本番優先）
# ---------------------------------------------------------
_FAST_CHAIN = None
if RAG_IMPL_FAST:
    try:
        # rag/fast_rag_chain.py に依存（既存構成準拠）
        from rag.fast_rag_chain import load_super_fast_vectorstore, get_super_fast_rag_chain  # type: ignore
        _VS = load_super_fast_vectorstore()
        # sources を後段で整形するため、source_documents が返るように組む
        _FAST_CHAIN = get_super_fast_rag_chain(_VS, return_source=True)
    except Exception as e:
        print(f"[services.rag_chain] FAST impl init failed -> fallback STANDARD: {e}")
        RAG_IMPL_FAST = False
        _FAST_CHAIN = None

# ---------------------------------------------------------
# STANDARD 実装（フォールバック）
# ---------------------------------------------------------
_STANDARD_QA = None
if not RAG_IMPL_FAST:
    try:
        from langchain_openai import ChatOpenAI
        from langchain.prompts import PromptTemplate
        from langchain.chains import RetrievalQA
        from langchain_community.vectorstores import FAISS

        # ★追加（方針1）：E5 prefix対応の埋め込み
        from langchain_core.embeddings import Embeddings
        from sentence_transformers import SentenceTransformer

        MODEL_NAME = os.getenv("STANDARD_RAG_MODEL", "gpt-3.5-turbo")
        PROMPT_PATH = os.getenv("RAG_PROMPT_PATH", "rag/prompt_template.txt")

        # ★追加：埋め込みモデル名（ingested_text.py / fast_rag_chain.py と揃える）
        EMBED_MODEL = os.getenv("EMBED_MODEL", "intfloat/multilingual-e5-small")

        class MyEmbedding(Embeddings):
            """Sentence-Transformers を使う埋め込み（E5 prefix対応）"""
            def __init__(self, model_name: str):
                self.model = SentenceTransformer(model_name)

            def embed_documents(self, texts):
                texts = [f"passage: {t}" for t in texts]
                return self.model.encode(texts, show_progress_bar=False).tolist()

            def embed_query(self, text):
                text = f"query: {text}"
                return self.model.encode(text).tolist()

        def _load_prompt() -> PromptTemplate:
            default_tpl = """あなたは有能なアシスタントです。与えられた「コンテキスト」の範囲内で、ユーザーの質問に日本語で簡潔かつ正確に答えてください。
コンテキスト:
{context}

質問:
{question}

制約:
- 不明な点は「分かりません」と述べ、推測しない
- 数値や用語はコンテキストの文面を優先
- 箇条書き主体で簡潔に
"""
            try:
                if os.path.exists(PROMPT_PATH):
                    with open(PROMPT_PATH, encoding="utf-8") as f:
                        tpl = f.read()
                else:
                    tpl = default_tpl
            except Exception:
                tpl = default_tpl
            return PromptTemplate(input_variables=["context", "question"], template=tpl)

        def _load_vectorstore() -> FAISS:
            # ★変更（方針1）：HuggingFaceEmbeddings -> MyEmbedding（prefix対応）
            emb = MyEmbedding(model_name=EMBED_MODEL)
            try:
                return FAISS.load_local(
                    VECTOR_DIR, emb,
                    index_name=INDEX_NAME,
                    allow_dangerous_deserialization=True,
                )
            except Exception:
                # 空のVSで起動だけは維持（回答はLLMに落ちないようガードすべき）
                return FAISS.from_texts(texts=[], embedding=emb)

        _PROMPT = _load_prompt()
        _VS = _load_vectorstore()
        _LLM = ChatOpenAI(model_name=MODEL_NAME, temperature=0)
        _STANDARD_QA = RetrievalQA.from_chain_type(
            llm=_LLM,
            chain_type="stuff",
            retriever=_VS.as_retriever(search_kwargs={"k": int(os.getenv("STANDARD_TOP_K", "3"))}),
            return_source_documents=True,  # ここは True 固定。返却時に INCLUDE_SOURCES で出し分け
            chain_type_kwargs={"prompt": _PROMPT},
        )
    except Exception as e:
        print(f"[services.rag_chain] STANDARD impl init failed: {e}")
        _STANDARD_QA = None


# ---------------------------------------------------------
# 公開インターフェース
# ---------------------------------------------------------
def get_rag_response(query: str) -> Tuple[str, List[str]]:
    """
    返り値: (answer: str, sources: list[str])
    - INCLUDE_SOURCES=false のときは sources は []
    - 呼び出し側は answer のみ UI に表示し、sources は JSON で保持すればOK
    """
    q = (query or "").strip()
    if not q:
        return "ご質問が空のようです。もう一度入力してください。", []

    # FAST
    if RAG_IMPL_FAST and _FAST_CHAIN is not None:
        try:
            res = _FAST_CHAIN.invoke({"query": q})
        except TypeError:
            # 実装差異がある場合の保険
            res = _FAST_CHAIN.invoke({"query": q, "question": q})

        ans = res.get("result", "") if isinstance(res, dict) else str(res)
        if not INCLUDE_SOURCES:
            return ans, []

        srcs: List[str] = []
        seen = set()
        for d in (res.get("source_documents") or []):
            md = getattr(d, "metadata", {}) or {}
            label = _format_source(md)
            if not label:
                continue
            if label in seen:
                continue
            seen.add(label)
            srcs.append(label)
        return ans, srcs

    # STANDARD
    if _STANDARD_QA is not None:
        res = _STANDARD_QA.invoke({"query": q})
        ans = res.get("result", "") if isinstance(res, dict) else str(res)
        if not INCLUDE_SOURCES:
            return ans, []

        srcs: List[str] = []
        seen = set()
        for d in (res.get("source_documents") or []):
            md = getattr(d, "metadata", {}) or {}
            label = _format_source(md)
            if not label:
                continue
            if label in seen:
                continue
            seen.add(label)
            srcs.append(label)
        return ans, srcs

    # 初期化失敗時の最終フォールバック
    return "現在準備中です。時間をおいてお試しください。", []
