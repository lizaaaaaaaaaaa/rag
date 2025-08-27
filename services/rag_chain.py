# services/rag_chain.py
"""
RAGフロントドア：
- RAG_IMPL=FAST（既定）: rag.fast_rag_chain を使用（FAQ優先やtimeout/kは .env で制御）
- RAG_IMPL=STANDARD: 典型的な RetrievalQA（安定だがやや重い）
呼び出し側は常に get_rag_response(query) を使えばOK。
"""
import os
from typing import List, Tuple

RAG_IMPL_FAST = os.getenv("RAG_IMPL", "FAST").upper() == "FAST"
INCLUDE_SOURCES = os.getenv("INCLUDE_SOURCES", "false").lower() == "true"

# ---------------------------------------------------------
# FAST 実装（本番推奨）
# ---------------------------------------------------------
_FAST_CHAIN = None
if RAG_IMPL_FAST:
    try:
        from rag.fast_rag_chain import load_super_fast_vectorstore, get_super_fast_rag_chain  # type: ignore
        _VS = load_super_fast_vectorstore()
        _FAST_CHAIN = get_super_fast_rag_chain(_VS, return_source=INCLUDE_SOURCES)
    except Exception as e:
        # ログだけ残して STANDARD へフォールバック
        print(f"[services.rag_chain] FAST impl init failed -> fallback STANDARD: {e}")
        RAG_IMPL_FAST = False
        _FAST_CHAIN = None

# ---------------------------------------------------------
# STANDARD 実装（フォールバック）
# ---------------------------------------------------------
_STANDARD_QA = None
if not RAG_IMPL_FAST:
    from langchain_openai import ChatOpenAI
    from langchain.prompts import PromptTemplate
    from langchain.chains import RetrievalQA
    from langchain_community.vectorstores import FAISS
    from langchain_community.embeddings import HuggingFaceEmbeddings

    VECTOR_DIR = os.getenv("VECTOR_DIR", "rag/vectorstore")
    INDEX_NAME = os.getenv("INDEX_NAME", "index")
    MODEL_NAME = os.getenv("STANDARD_RAG_MODEL", "gpt-3.5-turbo")
    PROMPT_PATH = os.getenv("RAG_PROMPT_PATH", "rag/prompt_template.txt")

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
        emb = HuggingFaceEmbeddings(model_name="intfloat/multilingual-e5-small")
        try:
            return FAISS.load_local(
                VECTOR_DIR, emb,
                index_name=INDEX_NAME,
                allow_dangerous_deserialization=True,
            )
        except Exception:
            return FAISS.from_texts(texts=[], embedding=emb)

    _PROMPT = _load_prompt()
    _VS = _load_vectorstore()
    _LLM = ChatOpenAI(model_name=MODEL_NAME, temperature=0)
    _STANDARD_QA = RetrievalQA.from_chain_type(
        llm=_LLM,
        chain_type="stuff",
        retriever=_VS.as_retriever(search_kwargs={"k": int(os.getenv("STANDARD_TOP_K", "3"))}),
        return_source_documents=INCLUDE_SOURCES,
        chain_type_kwargs={"prompt": _PROMPT},
    )

# ---------------------------------------------------------
# 公開インターフェース（呼び出しは常にこれだけ）
# ---------------------------------------------------------
def get_rag_response(query: str) -> Tuple[str, List[str]]:
    """
    返り値: (answer: str, sources: list[str])
    - INCLUDE_SOURCES=false のときは sources は []
    - 呼び出し側で出典を非表示にする場合は、answerのみ使えばOK
    """
    q = (query or "").strip()
    if not q:
        return "ご質問が空のようです。もう一度入力してください。", []

    # FAST実装
    if RAG_IMPL_FAST and _FAST_CHAIN is not None:
        res = _FAST_CHAIN.invoke({"query": q})
        ans = res.get("result", "") if isinstance(res, dict) else str(res)
        if not INCLUDE_SOURCES:
            return ans, []
        srcs: List[str] = []
        for d in res.get("source_documents", []) or []:
            md = getattr(d, "metadata", {}) or {}
            src = (md.get("source", "") or "").replace("/tmp/", "")
            page = md.get("page") or md.get("page_number") or md.get("pageIndex")
            label = f"{src}" + (f" (p{page})" if page is not None else "")
            if src:
                srcs.append(label)
        return ans, srcs

    # STANDARD実装
    if _STANDARD_QA is not None:
        res = _STANDARD_QA.invoke({"query": q})
        ans = res.get("result", "") if isinstance(res, dict) else str(res)
        if not INCLUDE_SOURCES:
            return ans, []
        srcs: List[str] = []
        for d in res.get("source_documents", []) or []:
            md = getattr(d, "metadata", {}) or {}
            src = (md.get("source", "") or "").replace("/tmp/", "")
            page = md.get("page") or md.get("page_number") or md.get("pageIndex")
            label = f"{src}" + (f" (p{page})" if page is not None else "")
            if src:
                srcs.append(label)
        return ans, srcs

    # どちらも初期化失敗時（最終フォールバック）
    return "現在準備中です。時間をおいてお試しください。", []
