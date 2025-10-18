# -*- coding: utf-8 -*-
"""
rag/fast_rag_chain.py — 完全修正版（最小影響・即時反映対応・伏字ガード）

目的:
- 既存I/Fを維持しつつ、アップロード直後にRAGへ**即時反映**できるようにする
- RetrievalQAのキー差異に**両対応**（{"query", "question"} を同時に渡す）
- ベクトルストアがローカルに無い場合、**任意でGCS補完**を試みる
- 🔒 回答の最終段で **伏字/プレースホルダ（○○、〇〇、××、XXXX、TBD、？？？）を排除**し、
  かつ**文末を必ず完結**させる（Cloud Run経路でも常に有効）

主な公開関数:
- load_super_fast_vectorstore() -> FAISS
- get_super_fast_rag_chain(vectorstore=None, return_source=True) -> UltraFastFAQChain
- refresh_vectorstore(force=False) -> FAISS   # ★追加（即時反映用）

互換性:
- 既存の UltraFastFAQChain / FAST_RAG_* 環境変数の動作は維持

ENV:
- VECTOR_DIR (default: rag/vectorstore)
- INDEX_NAME (default: index)
- FAST_RAG_MODEL (default: gpt-3.5-turbo)
- FAST_RAG_TOP_K (default: 10)
- FAST_RAG_TIMEOUT (default: 10.0)
- FAST_RAG_FAQ_FIRST (default: true)
- RAG_RELOAD_COOLDOWN_SEC (default: 3)
- VECTORSTORE_TRY_GCS_SYNC (default: true)  # ローカルに index.* がない時のみGCS補完
- RAG_PROMPT_PATH (default: rag/prompt_template.txt)
"""
from __future__ import annotations

import os
import sys
import pathlib
import threading
import time
import concurrent.futures
from typing import Optional, Dict, Any
import logging
import re  # ★ 伏字サニタイズ用

# --- add: ensure project root in sys.path for local runs ---
# /rag/fast_rag_chain.py -> /<project-root>
ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logger = logging.getLogger(__name__)

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
FAST_RAG_TIMEOUT = float(os.getenv("FAST_RAG_TIMEOUT", "10"))                   # RAG呼び上限秒
FAST_RAG_TOP_K = int(os.getenv("FAST_RAG_TOP_K", "10"))                         # 検索k

VECTOR_DIR = os.getenv("VECTOR_DIR", "rag/vectorstore")
INDEX_NAME = os.getenv("INDEX_NAME", "index")
MODEL_NAME = os.getenv("FAST_RAG_MODEL", "gpt-3.5-turbo")                       # OpenAIモデル名
PROMPT_PATH = os.getenv("RAG_PROMPT_PATH", "rag/prompt_template.txt")

# 追加: 即時反映/補完関連
RAG_RELOAD_COOLDOWN_SEC = int(os.getenv("RAG_RELOAD_COOLDOWN_SEC", "3"))
VECTORSTORE_TRY_GCS_SYNC = os.getenv("VECTORSTORE_TRY_GCS_SYNC", "true").lower() == "true"


# =========================
# 伏字サニタイズ（最終ガード）
# =========================
_PLACEHOLDER_RE = re.compile(r"(○○|〇〇|××|X{2,}|XXXX|TBD|？？？)")

def _sanitize_answer(text: str) -> str:
    """伏字を排除し、文末を必ず完結させる最終ガード。"""
    if not text:
        return text
    t = _PLACEHOLDER_RE.sub("（資料に記載なし）", str(text))
    if not t.endswith(("。", "！", "？", ".", "!", "?")):
        # ぶら下がり読点を句点に閉じる
        if t.endswith("、"):
            t = t[:-1] + "。"
        else:
            t += "。"
    return t


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
_LAST_VS_LOADED_AT: float = 0.0


# =========================
# パス補助
# =========================

def _index_paths() -> tuple[str, str]:
    """ローカルの index ファイルのパスを返す。"""
    base = pathlib.Path(VECTOR_DIR)
    faiss_path = base / f"{INDEX_NAME}.faiss"
    store_path = base / f"{INDEX_NAME}.pkl"
    return str(faiss_path), str(store_path)


# =========================
# プロンプト/埋め込み/LLM
# =========================

def _load_prompt() -> PromptTemplate:
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
    global _EMB
    if _EMB:
        return _EMB
    with _emb_lock:
        if _EMB is None:
            _EMB = HuggingFaceEmbeddings(model_name="intfloat/multilingual-e5-small")
    return _EMB


def _load_llm() -> ChatOpenAI:
    """可能なら llm/llm_runner.get_cached_llm_instance() を使用。無ければ ChatOpenAI を直接ロード。"""
    global _LLM
    if _LLM:
        return _LLM
    with _llm_lock:
        if _LLM is not None:
            return _LLM
        try:
            try:
                from llm.llm_runner import get_cached_llm_instance  # type: ignore
            except Exception:
                from llm_runner import get_cached_llm_instance  # type: ignore
            _LLM = get_cached_llm_instance()
        except Exception:
            _LLM = ChatOpenAI(model_name=MODEL_NAME, temperature=0)
    return _LLM


# =========================
# GCS補完（任意）
# =========================

def _ensure_local_index() -> None:
    """ローカルに index が無い場合のみ、任意でGCSから補完を試みる。失敗は無視。"""
    if not VECTORSTORE_TRY_GCS_SYNC:
        return
    faiss_path, store_path = _index_paths()
    if os.path.exists(faiss_path) and os.path.exists(store_path):
        return
    try:
        from utils.gcs_client import download_if_exists  # type: ignore
        # 一般的な配置想定: vectorstore/<index>.*
        remote_faiss = f"vectorstore/{INDEX_NAME}.faiss"
        remote_store = f"vectorstore/{INDEX_NAME}.pkl"
        d1 = download_if_exists(remote_faiss, faiss_path)
        d2 = download_if_exists(remote_store, store_path)
        if d1 or d2:
            logger.info("[RAG] vectorstore synced from GCS (partial=%s)", d1 != d2)
    except Exception as e:  # pragma: no cover
        logger.info("[RAG] skip optional GCS sync: %s", e)


# =========================
# VectorStore ロード/キャッシュ/リロード
# =========================

def load_super_fast_vectorstore() -> FAISS:
    """FAISSをロード（allow_dangerous_deserialization=True）。
    失敗時は空インデックスにフォールバック（問い合わせ経路を維持）。"""
    global _VS, _LAST_VS_LOADED_AT
    if _VS:
        return _VS
    with _vs_lock:
        if _VS is not None:
            return _VS
        _ensure_local_index()
        emb = _load_embeddings()
        try:
            _VS = FAISS.load_local(
                VECTOR_DIR,
                emb,
                index_name=INDEX_NAME,
                allow_dangerous_deserialization=True,
            )
            # 規模ログ（デバッグ用）
            try:
                ntotal = getattr(getattr(_VS, "index", None), "ntotal", None)
                if ntotal is not None:
                    logger.info("[RAG] faiss.ntotal=%s", ntotal)
            except Exception:
                pass
        except Exception:
            _VS = FAISS.from_texts(texts=[], embedding=emb)
        _LAST_VS_LOADED_AT = time.time()
    return _VS


def refresh_vectorstore(force: bool = False) -> FAISS:
    """取り込み直後などに呼ぶ。キャッシュを破棄して再ロード（クールダウンあり）。"""
    global _VS, _LAST_VS_LOADED_AT
    with _vs_lock:
        now = time.time()
        if (not force) and (now - _LAST_VS_LOADED_AT < RAG_RELOAD_COOLDOWN_SEC):
            logger.info("[RAG] refresh skipped by cooldown")
            return _VS  # type: ignore
        _VS = None
    # すぐにロードしてウォームアップ
    vs = load_super_fast_vectorstore()
    logger.info("[RAG] vectorstore refreshed")
    return vs


# =========================
# チェーン構築
# =========================

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
_FAQ: Dict[str, str] = {}


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
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    def invoke(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        query = (inputs.get("query") or inputs.get("question") or "").strip()
        if not query:
            return {"result": _sanitize_answer("ご質問が空のようです。もう一度入力してください。"),
                    "source_documents": []}

        # 1) FAQ即答（任意）
        if FAST_RAG_FAQ_FIRST:
            faq = get_ultra_fast_cached_response(query)
            if faq:
                return {"result": _sanitize_answer(faq), "source_documents": []}

        # 2) RAG実行（タイムボックス）
        #    🔧 両キーを渡して環境差に対応
        future = self.executor.submit(self.base_chain.invoke, {"query": query, "question": query})
        try:
            res = future.result(timeout=FAST_RAG_TIMEOUT)
        except concurrent.futures.TimeoutError:
            return {
                "result": _sanitize_answer("回答に時間がかかっています。別の聞き方でお試しください。"),
                "source_documents": [],
            }
        except Exception:
            return {
                "result": _sanitize_answer("うまく処理できませんでした。時間をおいて再度お試しください。"),
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

        # ★ 最終ガード適用（伏字排除 & 句点で閉じる）
        result_text = _sanitize_answer(result_text)

        return {"result": result_text, "source_documents": src_docs}


# =========================
# エントリポイント
# =========================

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