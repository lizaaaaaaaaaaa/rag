# api/routers/chat_unified.py
# 統合チャット（固定テンプレ & 出典非表示(既定) & RAG優先 & 資金計画の軽量推定）
from __future__ import annotations

import os
import re
import time
import logging
import importlib
import sys
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from contextlib import nullcontext

# -------------------------------
# 1) import パスを自己修復（llm/, services/, rag/ を拾えるように）
# -------------------------------
_THIS = Path(__file__).resolve()
_PROJECT_ROOT = _THIS.parents[2] if len(_THIS.parents) >= 2 else _THIS.parent
for _p in ("", "llm", "services", "rag", "utils", "api", "api/routers"):
    _pp = str((_PROJECT_ROOT / _p).resolve())
    if _pp not in sys.path:
        sys.path.append(_pp)

def _safe_import(modname: str, fallback: Optional[object] = None):
    try:
        return importlib.import_module(modname)
    except Exception:
        return fallback

logger = logging.getLogger("chat_unified")
router = APIRouter()

# -------------------------------
# 2) 依存（ゆるい参照）
# -------------------------------
tracer = type("T", (), {"start_span": staticmethod(lambda *_a, **_k: nullcontext())})()
monitor = type("M", (), {"log_event": staticmethod(lambda *_a, **_k: None)})()
web_search = _safe_import("utils.web_search", None)

def _noop_should_use_web_search(q: str) -> bool:  # 検索ヒントのUI用フラグ
    return False

should_use_web_search = getattr(web_search, "should_use_web_search", _noop_should_use_web_search)

# -------------------------------
# 3) UTM付き固定リンク（LINE リッチメニュー）
# -------------------------------
def _with_utm(url: str, campaign: str, ab: str = "A") -> str:
    if "?" in url:
        return f"{url}&utm_source=line&utm_medium=richmenu&utm_campaign={campaign}&utm_content=ai_menu&ab={ab}"
    return f"{url}?utm_source=line&utm_medium=richmenu&utm_campaign={campaign}&utm_content=ai_menu&ab={ab}"

AI_CONSULT_URL = "https://liff.line.me/LIFF_ID_AI?state=rag_home"
AI_SITE_URL    = "https://liff.line.me/LIFF_ID_SITE?state=rag_home"
BUDGET_URL     = "https://liff.line.me/LIFF_ID_BUDGET?state=rm_ai_loan"

ai_consult_link = _with_utm(AI_CONSULT_URL, "ai_consult", ab="A")
ai_site_link    = _with_utm(AI_SITE_URL,   "ai_site",    ab="A")
budget_link     = _with_utm(BUDGET_URL,    "budget",     ab="A")

RICHMENU_FIXED_RESPONSES: Dict[str, str] = {
    "ai_consult": f"AI相談を開始します。うまくいかない場合は {ai_consult_link} から開いてください。",
    "site":       f"WebサイトのAIチャットは {ai_site_link} です。使い分けてご利用ください。",
    "budget":     f"資金計画の簡易試算はこちら {budget_link} からどうぞ。",
}

def _detect_richmenu_press(q: str) -> Optional[str]:
    q2 = (q or "").strip().lower()
    if "ai相談" in q2 or "ai_consult" in q2:
        return "ai_consult"
    if "サイト" in q2 or "site" in q2:
        return "site"
    if "資金計画" in q2 or "budget" in q2:
        return "budget"
    return None

def is_richmenu_pressed(q: str) -> Optional[str]:
    return _detect_richmenu_press(q)

# -------------------------------
# 4) RAG フロントドア
#    旧/新どちらの入口にも対応:
#      - services.rag_processing_service.ask_rag (旧)
#      - rag_chain.get_rag_response / services.rag_chain.get_rag_response (新)
# -------------------------------
_INCLUDE_SOURCES = os.getenv("INCLUDE_SOURCES", "false").lower() == "true"

# 旧I/F（あれば使う）
_rag_mod_v1 = _safe_import("services.rag_processing_service", None)
_ask_rag = getattr(_rag_mod_v1, "ask_rag", None)

# 新I/F（優先）
_rag_mod_v2 = _safe_import("rag_chain", None) or _safe_import("services.rag_chain", None)
_get_rag_response = getattr(_rag_mod_v2, "get_rag_response", None)

def _rag_answer(q: str) -> Tuple[str, List[str]]:
    """
    RAGの標準入口。返り値は (answer, sources)。
    出典非表示の場合は sources は [] で返す。
    """
    # 旧I/F: services.rag_processing_service.ask_rag
    if callable(_ask_rag):
        try:
            out = _ask_rag(q, include_sources=_INCLUDE_SOURCES)
            ans = _strip_citations(_to_text(out))
            return (ans, []) if not _INCLUDE_SOURCES else (ans, out.get("sources", []) if isinstance(out, dict) else [])
        except Exception:
            logger.exception("RAG(ask_rag) failed")

    # 新I/F: rag_chain.get_rag_response / services.rag_chain.get_rag_response
    if callable(_get_rag_response):
        try:
            ans, srcs = _get_rag_response(q)  # (str, list[str]) を想定
            ans = _strip_citations(_to_text(ans))
            return (ans, [] if not _INCLUDE_SOURCES else (srcs or []))
        except Exception:
            logger.exception("RAG(get_rag_response) failed")

    return "", []

# -------------------------------
# 5) LLM フォールバック
# -------------------------------
_llm_mod = _safe_import("llm.llm_runner", None)
_openai_runner = getattr(_llm_mod, "chat_completion", None)

def _llm_answer(prompt: str) -> str:
    if _openai_runner:
        try:
            out = _openai_runner(prompt)
            return _strip_citations(_to_text(out))
        except Exception:
            logger.exception("LLM runner failed; fallback to minimal client")
    try:
        import openai  # type: ignore
        client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        model = os.getenv("OPENAI_MODEL_NAME", "gpt-3.5-turbo")
        temperature = float(os.getenv("OPENAI_TEMPERATURE", "0.1"))
        max_tokens = int(os.getenv("OPENAI_MAX_TOKENS", os.getenv("MAX_NEW_TOKENS", "900")))
        rsp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        text = rsp.choices[0].message.content or ""
        fin = rsp.choices[0].finish_reason or ""
        if fin == "length":
            max_tokens2 = int(os.getenv("OPENAI_MAX_TOKENS_CONT", os.getenv("MAX_NEW_TOKENS_CONT", "600")))
            rsp2 = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": text},
                    {"role": "user", "content": "続きだけを日本語で、簡潔に出してください。"}
                ],
                temperature=temperature,
                max_tokens=max_tokens2,
            )
            text += "\n" + (rsp2.choices[0].message.content or "")
        return _strip_citations(text)
    except Exception:
        logger.exception("openai.ChatCompletions fallback failed")
        return _strip_citations("")

# -------------------------------
# 6) テキスト整形 & 質問の軽い正規化
# -------------------------------
def _strip_citations(text: str) -> str:
    if not text:
        return text
    text = re.sub(r"^\s*(参考|資料|出典)\s*[:：].*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"【出典】[\s\S]*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s*\(p\.\s*\d+\s*\)\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # 伏字(○○市/△△町/××区…)の抑止
    text = re.sub(r"[○◯〇×]{2,}(市|区|町|村)", "（資料に記載なし）", text)
    text = re.sub(r"[○◯〇×]+[-ー]?(エリア|地域|方面)", "（資料に記載なし）", text)
    return text.strip()

def _to_text(o: Any) -> str:
    if isinstance(o, str):
        return o
    if isinstance(o, dict):
        for k in ("answer", "output", "result", "text", "final"):
            if isinstance(o.get(k), str):
                return str(o[k])
    return str(o)

# よくある表記ゆれを補う（クエリの当たりを広げる）
def _normalize_query(q: str) -> str:
    if not q:
        return q
    q2 = q.replace("　", " ").strip()
    # 施工エリア系
    q2 = q2.replace("施工可能エリア", "対応エリア 対応地域 施工対応地域 施工エリア")
    # カタカナのゆれ（必要に応じて追加）
    q2 = q2.replace("キノエ", "キノエ KINOE Kinoe")
    return q2

# -------------------------------
# 7) 「資金計画」検出（簡易）
# -------------------------------
class FinancialRequest(BaseModel):
    annual_income: Optional[int] = None
    age: Optional[int] = None
    own_funds: Optional[int] = None
    monthly_saving: Optional[int] = None

def _is_financial_query(q: str) -> bool:
    q2 = (q or "").replace("　", " ")
    keys = ("資金計画", "ローン", "借入", "返済", "予算", "年収", "頭金", "月々")
    return any(k in q2 for k in keys)

def _extract_financial(q: str) -> FinancialRequest:
    import re as _re
    nums = [int(n) for n in _re.findall(r"\d+", q or "")]
    fr = FinancialRequest()
    if nums:
        fr.annual_income = nums[0]
    return fr

def _estimate_budget(fr: FinancialRequest) -> Tuple[str, bool]:
    if fr.annual_income and fr.annual_income > 0:
        est = int(fr.annual_income * 7 / 10)  # 控えめ
        return (f"年収{fr.annual_income:,}円の場合の概算上限はおよそ{est:,}円です。詳細は個別条件で前後します。", True)
    return ("資金計画は年収や頭金などの条件が必要です。年収や頭金の目安を教えてください。", False)

# -------------------------------
# 8) API モデル & ルート
# -------------------------------
class ChatRequest(BaseModel):
    question: str
    source: Optional[str] = "web"  # "web" or "line"

@router.post("/chat")
def chat(req: ChatRequest) -> Dict[str, Any]:
    raw = (req.question or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty question")
    resp = _generate_response_sync(raw, req.source or "web")
    resp["elapsed"] = round(resp.get("elapsed", 0.0), 3)
    return resp

# -------------------------------
# 9) メイン入口（main.py から await される）
# -------------------------------
async def generate_response(question: str,
                            platform: str = "web",
                            username: str | None = None,
                            mode: str = "auto") -> Dict[str, Any]:
    """
    戻り値: {answer, sources, source, status}
    """
    t0 = time.time()
    raw = (question or "").strip()

    # a) リッチメニュー押下は即テンプレ
    pressed = None
    try:
        pressed = is_richmenu_pressed(raw)
    except Exception:
        pressed = None
    if not pressed:
        pressed = _detect_richmenu_press(raw)
    if pressed:
        reply = RICHMENU_FIXED_RESPONSES.get(pressed, "")
        return {"answer": reply, "sources": [], "source": "richmenu", "status": "ok", "elapsed": time.time() - t0}

    # b) 簡易「資金計画」
    if _is_financial_query(raw):
        data = _extract_financial(raw)
        text, ok = _estimate_budget(data)
        if ok:
            return {"answer": text, "sources": [], "source": "finance", "status": "ok", "elapsed": time.time() - t0}

    # c) まず RAG を試す（ここで表記ゆれを軽く正規化）
    norm = _normalize_query(raw)
    ans, srcs = _rag_answer(norm)
    if ans:
        return {
            "answer": ans,
            "sources": srcs if _INCLUDE_SOURCES else [],
            "source": "rag",
            "status": "ok",
            "elapsed": time.time() - t0,
        }

    # d) Web検索ヒント（UIフラグ）
    try:
        use_web = bool(should_use_web_search(raw))
    except Exception:
        use_web = False

    # e) RAG厳格モードならここで終了
    if os.getenv("STRICT_RAG_ONLY", "false").lower() == "true":
        safe_msg = "資料に基づく情報が見つかりませんでした。もう少し条件（例：正式な資料名や具体のプラン名）を教えてください。"
        return {"answer": safe_msg, "sources": [], "source": "safety", "status": "ok", "used_web_search": use_web, "elapsed": time.time() - t0}

    # f) LLM フォールバック
    llm_text = _llm_answer(raw)
    return {"answer": llm_text, "sources": [], "source": "llm", "status": "ok", "used_web_search": use_web, "elapsed": time.time() - t0}

# -------------------------------
# 10) 同期互換（FastAPI の sync ルートからも使う）
# -------------------------------
def _generate_response_sync(question: str, platform: str = "web") -> Dict[str, Any]:
    return _awaitless(generate_response(question, platform))

def _awaitless(coro):
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        if loop.is_running():
            return {"answer": "処理中です。", "sources": [], "source": "async", "status": "ok"}
        return loop.run_until_complete(coro)
    except Exception:
        return {"answer": "ただいま処理が混み合っています。少し時間をおいてお試しください。", "sources": [], "source": "error", "status": "degraded"}

@router.get("/chat/ping")
def ping() -> Dict[str, Any]:
    return {"pong": True}

# 内部フック（main.py 側の切替用）
unified_generator = sys.modules[__name__]
