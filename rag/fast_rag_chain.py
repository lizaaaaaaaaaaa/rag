# rag/fast_rag_chain.py
"""
超高速RAG（FASTモード）
- FAQ即答: FAST_RAG_FAQ_FIRST=true のとき完全一致FAQで即応
- RAG本体: FAISS + e5-multilingual + RetrievalQA
- タイムボックス: FAST_RAG_TIMEOUT 秒でタイムアウト（既定 5s）
- 検索幅: FAST_RAG_TOP_K 件（既定 3）
- LLM: 可能なら llm/llm_runner.get_cached_llm_instance() を使用。なければ ChatOpenAI を直接使用。

公開関数:
- load_super_fast_vectorstore() -> FAISS
- get_super_fast_rag_chain(vectorstore=None, return_source=True) -> UltraFastFAQChain
  - chain.invoke({"query": "..."}) -> {"result": str, "source_documents": list}
"""

from __future__ import annotations

import os
import sys
import pathlib
import threading
import concurrent.futures
from typing import Optional, Dict, Any

# --- add: ensure project root in sys.path for local runs ---
# /rag/fast_rag_chain.py -> /<project-root>
ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# LangChain / VectorStore
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_openai import ChatOpenAI
from langchain.prompts import PromptTemplate
from langchain.chains import RetrievalQA


# =========================
# 環境変数スイッチ
# =========================
FAST_RAG_FAQ_FIRST = os.getenv("FAST_RAG_FAQ_FIRST", "true").lower() == "true"  # FAQ優先
FAST_RAG_TIMEOUT = float(os.getenv("FAST_RAG_TIMEOUT", "5.0"))                 # RAG呼び上限秒
FAST_RAG_TOP_K = int(os.getenv("FAST_RAG_TOP_K", "3"))                         # 検索k

VECTOR_DIR = os.getenv("VECTOR_DIR", "rag/vectorstore")
INDEX_NAME = os.getenv("INDEX_NAME", "index")
MODEL_NAME = os.getenv("FAST_RAG_MODEL", "gpt-3.5-turbo")                      # OpenAIモデル名
PROMPT_PATH = os.getenv("RAG_PROMPT_PATH", "rag/prompt_template.txt")


# =========================
# グローバル・シングルトン
# =========================
_emb_lock = threading.Lock()
_vs_lock = threading.Lock()
_llm_lock = threading.Lock()

_EMB: Optional[HuggingFaceEmbeddings] = None
_VS: Optional[FAISS] = None
_LLM: Optional[ChatOpenAI] = None
_PROMPT: Optional[PromptTemplate] = None


def _load_prompt() -> PromptTemplate:
    """テンプレートファイルが無ければ安全な既定にフォールバック。"""
    global _PROMPT
    if _PROMPT:
        return _PROMPT
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
    _PROMPT = PromptTemplate(input_variables=["context", "question"], template=tpl)
    return _PROMPT


def _load_embeddings() -> HuggingFaceEmbeddings:
    """軽量・日本語対応（e5-multilingual-small）"""
    global _EMB
    if _EMB:
        return _EMB
    with _emb_lock:
        if _EMB is None:
            _EMB = HuggingFaceEmbeddings(model_name="intfloat/multilingual-e5-small")
    return _EMB


def load_super_fast_vectorstore() -> FAISS:
    """
    起動時に一度だけFAISSをロード（allow_dangerous_deserialization=True）。
    失敗時は空インデックスにフォールバック（問い合わせ経路が落ちないように）。
    """
    global _VS
    if _VS:
        return _VS
    with _vs_lock:
        if _VS is not None:
            return _VS
        emb = _load_embeddings()
        try:
            _VS = FAISS.load_local(
                VECTOR_DIR,
                emb,
                index_name=INDEX_NAME,
                allow_dangerous_deserialization=True,
            )
        except Exception:
            # 空のインデックス（からでも動くように）
            _VS = FAISS.from_texts(texts=[], embedding=emb)
    return _VS


def _load_llm() -> ChatOpenAI:
    """
    可能なら llm/llm_runner.get_cached_llm_instance() を使用。
    無ければ ChatOpenAI を直接ロード。
    """
    global _LLM
    if _LLM:
        return _LLM
    with _llm_lock:
        if _LLM is not None:
            return _LLM
        try:
            # 正規: パッケージ llm 配下
            try:
                from llm.llm_runner import get_cached_llm_instance  # type: ignore
            except Exception:
                # 予備: ルート直下に llm_runner.py がある旧構成
                from llm_runner import get_cached_llm_instance  # type: ignore
            _LLM = get_cached_llm_instance()
        except Exception:
            _LLM = ChatOpenAI(model_name=MODEL_NAME, temperature=0)
    return _LLM


def _build_retrieval_chain(vectorstore: FAISS, return_source: bool) -> RetrievalQA:
    prompt = _load_prompt()
    llm = _load_llm()
    retriever = vectorstore.as_retriever(search_kwargs={"k": FAST_RAG_TOP_K})
    chain = RetrievalQA.from_chain_type(
        llm=llm,
        chain_type="stuff",
        retriever=retriever,
        return_source_documents=return_source,
        chain_type_kwargs={"prompt": prompt},
    )
    return chain


# =========================
# FAQ/キャッシュ（必要に応じて拡充）
# =========================
_FAQ: Dict[str, str] = {
    # 例: "標準仕様は？": "当社の標準仕様は〜です。詳細はサイトをご覧ください。"
}
def get_ultra_fast_cached_response(query: str) -> Optional[str]:
    # 誤爆防止のため完全一致のみ
    return _FAQ.get(query.strip())


class UltraFastFAQChain:
    """
    - FAQで即答（FAST_RAG_FAQ_FIRST=true のとき）
    - 外したらRAGをスレッドで実行し、FAST_RAG_TIMEOUTでタイムアウト
    - .invoke({"query": str}) -> {"result": str, "source_documents": list}
    """
    def __init__(self, base_chain: RetrievalQA, return_source: bool):
        self.base_chain = base_chain
        self.return_source = return_source
        # max_workers=1 で順序を保ちつつ、呼び出し側とは別スレッドで実行
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    def invoke(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        query = (inputs.get("query") or inputs.get("question") or "").strip()
        if not query:
            return {"result": "ご質問が空のようです。もう一度入力してください。", "source_documents": []}

        # 1) FAQ即答（任意）
        if FAST_RAG_FAQ_FIRST:
            faq = get_ultra_fast_cached_response(query)
            if faq:
                return {"result": faq, "source_documents": []}

        # 2) RAG実行（タイムボックス）
        future = self.executor.submit(self.base_chain.invoke, {"query": query})
        try:
            res = future.result(timeout=FAST_RAG_TIMEOUT)
        except concurrent.futures.TimeoutError:
            return {
                "result": "回答に時間がかかっています。別の聞き方でお試しください。",
                "source_documents": [],
            }
        except Exception:
            return {
                "result": "うまく処理できませんでした。時間をおいて再度お試しください。",
                "source_documents": [],
            }

        # LangChainの戻り型に合わせて整形
        if isinstance(res, dict):
            result_text = res.get("result", "") or ""
            src_docs = res.get("source_documents", []) or []
        else:
            result_text = str(res)
            src_docs = []

        if not self.return_source:
            src_docs = []

        return {"result": result_text, "source_documents": src_docs}


def get_super_fast_rag_chain(
    vectorstore: Optional[FAISS] = None,
    return_source: bool = True,
) -> UltraFastFAQChain:
    """
    入口はこの関数だけでOK：
      vs = load_super_fast_vectorstore()
      chain = get_super_fast_rag_chain(vs, return_source=False)
      chain.invoke({"query": "◯◯とは？"})
    """
    vs = vectorstore or load_super_fast_vectorstore()
    base = _build_retrieval_chain(vs, return_source)
    return UltraFastFAQChain(base, return_source)
