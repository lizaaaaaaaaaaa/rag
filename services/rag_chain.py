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
  VECTOR_INDEX_NAME / INDEX_NAME
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

# ★修正ポイント：ingest / fast_rag_chain と index 名を完全に揃える（VECTOR_INDEX_NAME 優先）
INDEX_NAME = os.getenv("VECTOR_INDEX_NAME") or os.getenv("INDEX_NAME", "index")

# ✅重要：FAST実装（rag.fast_rag_chain）は import 時に env を読むので、
#         services 側で決めた値を import 前に env に反映しておく（既に指定があれば上書きしない）
os.environ.setdefault("VECTOR_DIR", VECTOR_DIR)
os.environ.setdefault("INDEX_NAME", INDEX_NAME)

# ---------------------------------------------------------
# 出典ラベル整形
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
    """
    name = md.get("original_filename")
    gcs_path = md.get("gcs_path") or ""
    if not name and gcs_path:
        name = _basename(gcs_path)
    if not name:
        name = _basename(md.get("source", ""))

    if not name:
        return None

    if md.get("original_filename"):
        if re.match(r"^tmp[^/\\]*\.pdf$", name, re.IGNORECASE):
            name = md["original_filename"]

    page = md.get("page")
    if page is None:
        page = md.get("page_number") or md.get("pageIndex")

    return f"{name} (p.{page})" if page is not None else name


# ---------------------------------------------------------
# FAST 実装
# ---------------------------------------------------------
_FAST_CHAIN = None
if RAG_IMPL_FAST:
    try:
        from rag.fast_rag_chain import load_super_fast_vectorstore, get_super_fast_rag_chain  # type: ignore

        _VS = load_super_fast_vectorstore()
        _FAST_CHAIN = get_super_fast_rag_chain(_VS, return_source=True)
    except Exception as e:
        print(f"[services.rag_chain] FAST impl init failed -> fallback STANDARD: {e}")
        RAG_IMPL_FAST = False
        _FAST_CHAIN = None


# ---------------------------------------------------------
# STANDARD 実装
# ---------------------------------------------------------
_STANDARD_QA = None
if not RAG_IMPL_FAST:
    try:
        from langchain_openai import ChatOpenAI
        from langchain.prompts import PromptTemplate
        from langchain.chains import RetrievalQA
        from langchain_community.vectorstores import FAISS
        from langchain_core.embeddings import Embeddings
        from sentence_transformers import SentenceTransformer

        MODEL_NAME = os.getenv("STANDARD_RAG_MODEL", "gpt-3.5-turbo")
        PROMPT_PATH = os.getenv("RAG_PROMPT_PATH", "rag/prompt_template.txt")
        EMBED_MODEL = os.getenv("EMBED_MODEL", "intfloat/multilingual-e5-small")

        class MyEmbedding(Embeddings):
            def __init__(self, model_name: str):
                self.model = SentenceTransformer(model_name)

            def embed_documents(self, texts):
                texts = [f"passage: {t}" for t in texts]
                return self.model.encode(texts, show_progress_bar=False).tolist()

            def embed_query(self, text):
                return self.model.encode(f"query: {text}").tolist()

        def _load_prompt() -> PromptTemplate:
            default_tpl = """あなたは有能なアシスタントです。
コンテキスト:
{context}

質問:
{question}
"""
            if os.path.exists(PROMPT_PATH):
                with open(PROMPT_PATH, encoding="utf-8") as f:
                    return PromptTemplate(
                        input_variables=["context", "question"],
                        template=f.read(),
                    )
            return PromptTemplate(
                input_variables=["context", "question"],
                template=default_tpl,
            )

        def _load_vectorstore() -> FAISS:
            emb = MyEmbedding(EMBED_MODEL)
            try:
                return FAISS.load_local(
                    VECTOR_DIR,
                    emb,
                    index_name=INDEX_NAME,
                    allow_dangerous_deserialization=True,
                )
            except Exception:
                return FAISS.from_texts(texts=[], embedding=emb)

        _VS = _load_vectorstore()
        _LLM = ChatOpenAI(model_name=MODEL_NAME, temperature=0)
        _PROMPT = _load_prompt()

        _STANDARD_QA = RetrievalQA.from_chain_type(
            llm=_LLM,
            chain_type="stuff",
            retriever=_VS.as_retriever(search_kwargs={"k": int(os.getenv("STANDARD_TOP_K", "3"))}),
            return_source_documents=True,
            chain_type_kwargs={"prompt": _PROMPT},
        )
    except Exception as e:
        print(f"[services.rag_chain] STANDARD impl init failed: {e}")
        _STANDARD_QA = None


# ---------------------------------------------------------
# 公開インターフェース
# ---------------------------------------------------------
def get_rag_response(query: str) -> Tuple[str, List[str]]:
    q = (query or "").strip()
    if not q:
        return "ご質問が空です。", []

    if RAG_IMPL_FAST and _FAST_CHAIN is not None:
        res = _FAST_CHAIN.invoke({"query": q})
        ans = res.get("result", "")
        if not INCLUDE_SOURCES:
            return ans, []

        srcs, seen = [], set()
        for d in res.get("source_documents", []):
            label = _format_source(getattr(d, "metadata", {}) or {})
            if label and label not in seen:
                seen.add(label)
                srcs.append(label)
        return ans, srcs

    if _STANDARD_QA is not None:
        res = _STANDARD_QA.invoke({"query": q})
        ans = res.get("result", "")
        if not INCLUDE_SOURCES:
            return ans, []

        srcs, seen = [], set()
        for d in res.get("source_documents", []):
            label = _format_source(getattr(d, "metadata", {}) or {})
            if label and label not in seen:
                seen.add(label)
                srcs.append(label)
        return ans, srcs

    return "現在準備中です。", []
