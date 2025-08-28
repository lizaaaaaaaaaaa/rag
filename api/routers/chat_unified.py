# api/routers/chat_unified.py
# 統合チャット（固定テンプレ & 出典非表示 & RAG優先 & 資金計画の軽量推定）
from __future__ import annotations

import os
import re
import time
import logging
import importlib
import sys
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# -------------------------------
# 1) import パスを自己修復（llm/, services/, rag/ を拾えるように）
# -------------------------------
_THIS = Path(__file__).resolve()
_PROJECT_ROOT = _THIS.parents[2]  # <repo>/
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# -------------------------------
# 2) UTM 付与（存在しない場合でも動くフォールバック）
# -------------------------------
def _with_utm_fallback(url: str, source: str, ab: str | None = None) -> str:
    from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
    u = urlparse(url)
    q = dict(parse_qsl(u.query))
    q.setdefault("utm_source", "line")
    q.setdefault("utm_medium", "richmenu")
    q["utm_campaign"] = source
    if ab:
        q["ab"] = ab
    new_q = urlencode(q)
    return urlunparse((u.scheme, u.netloc, u.path, u.params, new_q, u.fragment))

try:
    from api.routers.line_utils import with_utm as _with_utm  # type: ignore
except Exception:
    _with_utm = _with_utm_fallback

# -------------------------------
# 3) 定数（必要なら本番の LIFF URL に置換）
# -------------------------------
AI_CONSULT_URL = "https://liff.line.me/LIFF_ID_AI?state=rag_home"
AI_SITE_URL    = "https://liff.line.me/LIFF_ID_SITE?state=rag_home"
BUDGET_URL     = "https://liff.line.me/LIFF_ID_BUDGET?state=rm_ai_loan"

ai_consult_link = _with_utm(AI_CONSULT_URL, "ai_consult", ab="A")
ai_site_link    = _with_utm(AI_SITE_URL,   "ai_site",    ab="A")
budget_link     = _with_utm(BUDGET_URL,    "budget",     ab="A")

# -------------------------------
# 4) web_search（存在しなくてもOK）
# -------------------------------
def _noop_should_use_web_search(_: str) -> bool:
    return False

def _noop_is_richmenu_pressed(_: str) -> Optional[str]:
    return None

try:
    try:
        from utils.web_search import should_use_web_search, is_richmenu_pressed
    except ModuleNotFoundError:
        from web_search import should_use_web_search, is_richmenu_pressed  # type: ignore
except Exception as e:
    logger.warning("web_search import fallback: %s", e)
    should_use_web_search = _noop_should_use_web_search  # type: ignore
    is_richmenu_pressed = _noop_is_richmenu_pressed      # type: ignore

# -------------------------------
# 5) LangSmith tracer が無くても動くように
# -------------------------------
try:
    try:
        from utils.langsmith_tracer import trace_span, RAGTracer
    except ModuleNotFoundError:
        from langsmith_tracer import trace_span, RAGTracer  # type: ignore
except Exception:
    def trace_span(_name: str):
        def _deco(fn):
            return fn
        return _deco

    class RAGTracer:  # type: ignore
        def start_span(self, *_a, **_k):
            class _CM:
                def __enter__(self): return self
                def __exit__(self, *exc): return False
            return _CM()
        def record(self, *_a, **_k): pass

tracer = RAGTracer()

# -------------------------------
# 6) RAG を完全 lazy-load に
# -------------------------------
_RAG = None

def _lazy_load_rag():
    """必要になった瞬間にだけRAGモジュールを解決（起動を軽くする）"""
    global _RAG
    if _RAG is not None:
        return _RAG
    for modname in (
        "api.services.rag_chain",
        "services.rag_chain",
        "rag.fast_rag_chain",
        "rag_chain",
        "fast_rag_chain",
    ):
        try:
            _RAG = importlib.import_module(modname)
            logger.info("RAG module loaded: %s", modname)
            break
        except Exception:
            continue
    return _RAG

def _rag_answer(question: str) -> Optional[str]:
    mod = _lazy_load_rag()
    if mod is None:
        return None
    try:
        # チェーンfactory候補
        chain = None
        for factory in (
            "get_ultra_fast_rag_chain",
            "get_super_fast_rag_chain",
            "build_fast_rag_chain",
            "get_rag_chain",
            "create_rag_chain",
        ):
            fn = getattr(mod, factory, None)
            if fn:
                chain = fn()
                break
        if chain is None:
            # 直接関数候補
            for direct in ("answer_with_rag", "rag_answer", "answer", "get_rag_response"):
                f = getattr(mod, direct, None)
                if f:
                    out = f(question)
                    return _strip_citations(_to_text(out))
            return None

        payload = {"question": question, "query": question, "input": question}
        if hasattr(chain, "invoke"):
            out = chain.invoke(payload)  # type: ignore[attr-defined]
        elif hasattr(chain, "run"):
            out = chain.run(question)    # type: ignore[attr-defined]
        else:
            out = chain(payload)         # call-able
        return _strip_citations(_to_text(out))
    except Exception as e:
        logger.exception("RAG failed: %s", e)
        return None

# -------------------------------
# 7) LLM フォールバック（llm_runner → OpenAI直 → 固定文）
# -------------------------------
def _llm_answer(prompt: str) -> str:
    # 7-1) llm_runner を優先（パッケージ/相対の両対応）
    try:
        try:
            from llm.llm_runner import chat_completion  # type: ignore
        except ModuleNotFoundError:
            from llm_runner import chat_completion  # type: ignore
        return _strip_citations(chat_completion(prompt))
    except Exception as e:
        logger.info("llm_runner fallback to OpenAI: %s", e)

    # 7-2) OpenAI 直（ENV優先で上限拡大 & 自動つづき）
    try:
        import openai  # type: ignore
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set")
        client = openai.OpenAI(api_key=api_key)  # type: ignore[attr-defined]

        model = os.getenv("OPENAI_MODEL_NAME", "gpt-3.5-turbo")
        temperature = float(os.getenv("OPENAI_TEMPERATURE", "0.1"))
        max_tokens = int(os.getenv("OPENAI_MAX_TOKENS", os.getenv("MAX_NEW_TOKENS", "900")))
        # 1回目
        rsp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        text = rsp.choices[0].message.content or ""
        fin = getattr(rsp.choices[0], "finish_reason", None)

        # 必要なら“続きだけ”もう1度取りに行く
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
    except Exception as e:
        logger.warning("OpenAI not available: %s", e)
        return "今のご質問について準備中です。もう一度お試しください。"

# -------------------------------
# 8) 出典/参考/資料 の行を全部消す
# -------------------------------
def _strip_citations(text: str) -> str:
    if not text:
        return text
    text = re.sub(r"^\s*(参考|資料|出典)\s*[:：].*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"【出典】[\s\S]*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s*\(p\.\s*\d+\s*\)\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def _to_text(o: Any) -> str:
    if isinstance(o, str):
        return o
    if isinstance(o, dict):
        for k in ("answer", "output", "result", "text", "final"):
            if isinstance(o.get(k), str):
                return str(o[k])
    return str(o)

# -------------------------------
# 9) :robot: のようなコロン表記 → Unicode 絵文字へ
# -------------------------------
_COLON_EMOJIS = {
    ":robot:": "🤖", ":globe_with_meridians:": "🌐", ":page_facing_up:": "📄",
    ":round_pushpin:": "📍", ":moneybag:": "💴", ":speech_balloon:": "💬",
    ":bulb:": "💡", ":mobile_phone:": "📱", ":sparkles:": "✨"
}
def _normalize_colon_emoji(s: str) -> str:
    for k, v in _COLON_EMOJIS.items():
        s = s.replace(k, v)
    return s

# -------------------------------
# 10) リッチメニューの固定テンプレ（抜粋）
# -------------------------------
RICHMENU_FIXED_RESPONSES: Dict[str, str] = {
    "follow_greeting": _normalize_colon_emoji("""こんにちは！キノエデザイン住まいAIコンシェルジュ（秋山住研）です。
この度は友だち追加ありがとうございます✨
まずはメニュー左上の「AI相談（24h）」から、 気になることを質問してみてください。

すぐ使えるメニューはこちら👇
🤖AI相談 / 📍来場予約 / 📄資料請求 / 💴資金計画 / 🌐サイト / 💬チャット

※匿名OK／保存OFF（既定） 
※AIの回答は必ずしも正しいとは限りません。➡ 最終案内はスタッフが行います。
※AIは24時間、担当者は当日〜翌営業日に返信します。
※ご使用の前に、必ず以下の取り扱いをご確認ください。
プライバシーポリシー：【https://preview.studio.site/live/EjOQljz1WJ/privacy-policy 】
利用規約：【https://preview.studio.site/live/EjOQljz1WJ/termsofuse/service 】
Cookie：【https://preview.studio.site/live/EjOQljz1WJ/cookie 】"""),

    "AI相談": _normalize_colon_emoji("""🤖 AI住まい相談を開始します！..."""),
    "AI住まいサイト": _normalize_colon_emoji("""🌐 AI住まいサイトのご案内..."""),
    "資料請求": _normalize_colon_emoji("""📄ありがとうございます！こちらからご覧いただけます。..."""),
    "展示場来場予約": _normalize_colon_emoji("""📍 展示場のご来場予約..."""),
    "資金計画": _normalize_colon_emoji("""💴 AI資金診断のご案内..."""),
    "チャット相談": _normalize_colon_emoji("""💬 スタッフとのご相談..."""),
}

RICHMENU_KEYWORD_MAPPING: Dict[str, str] = {
    "AI相談": "AI相談", ":robot: AI相談": "AI相談", "🤖 AI相談": "AI相談",
    "AI住まいサイト": "AI住まいサイト", "🌐 AI住まいサイト": "AI住まいサイト",
    "サイト": "AI住まいサイト", "ホームページ": "AI住まいサイト",
    "資料請求": "資料請求", "📄 資料請求": "資料請求", ":page_facing_up: 資料請求": "資料請求",
    "展示場来場予約": "展示場来場予約", "📍 展示場来場　予約": "展示場来場予約",
    "来場予約": "展示場来場予約", ":round_pushpin: 展示場来場　予約": "展示場来場予約",
    "資金計画": "資金計画", "💴 資金計画": "資金計画", "💰 資金計画": "資金計画",
    ":moneybag: 資金計画": "資金計画",
    "チャット相談": "チャット相談", "💬チャット相談": "チャット相談", "チャット": "チャット相談",
    ":speech_balloon: チャット相談": "チャット相談",
}

def _detect_richmenu_press(raw: str) -> Optional[str]:
    if not raw:
        return None
    msg = _normalize_colon_emoji(raw.strip())
    if msg in RICHMENU_FIXED_RESPONSES:
        return msg
    for k, mapped in RICHMENU_KEYWORD_MAPPING.items():
        if k in raw or k in msg:
            return mapped
    if msg in RICHMENU_KEYWORD_MAPPING:
        return RICHMENU_KEYWORD_MAPPING[msg]
    return None

# -------------------------------
# 11) 資金計画の最軽量推定（ユーザー入力をざっくり解析）
# -------------------------------
def _parse_money(s: str) -> Optional[int]:
    s = s.replace(",", "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*(万|万円|千|千円|円)?", s)
    if not m:
        return None
    val = float(m.group(1))
    unit = m.group(2) or ""
    if "万円" in unit or unit == "万":
        return int(val * 10000)
    if "千円" in unit or unit == "千":
        return int(val * 1000)
    if "円" in unit or unit == "":
        return int(val)
    return None

def _extract_financial(req: str) -> Dict[str, Optional[int | str]]:
    text = req.replace("：", ":")
    data: Dict[str, Optional[int | str]] = {
        "annual_income": None,
        "monthly_payment": None,
        "years": None,
        "family": None,
        "other_debt": None
    }
    m = re.search(r"(年収)\s*[:：]?\s*([0-9,\.万千円]+)", text)
    if m: data["annual_income"] = _parse_money(m.group(2))
    m = re.search(r"(毎月.*返済額|月.*返済)\s*[:：]?\s*([0-9,\.万千円]+)", text)
    if m: data["monthly_payment"] = _parse_money(m.group(2))
    m = re.search(r"(借入|期間|年数)\s*[:：]?\s*(\d+)\s*年", text)
    if m: data["years"] = int(m.group(2))
    m = re.search(r"(家族構成)\s*[:：]?\s*(.+)", text)
    if m: data["family"] = m.group(2).strip()
    m = re.search(r"(負担|ローン)\s*[:：]?\s*([0-9,\.万千円]+)", text)
    if m: data["other_debt"] = _parse_money(m.group(2))
    return data

def _is_financial_query(message: str) -> bool:
    keys = ("年収", "返済", "借入", "家族構成", "ローン")
    return any(k in message for k in keys)

def _estimate_budget(data: Dict[str, Optional[int | str]]) -> Tuple[str, bool]:
    income = data.get("annual_income") or 0
    monthly = data.get("monthly_payment") or 0
    years = data.get("years") or 35
    other = data.get("other_debt") or 0

    if not monthly and income:
        monthly = int((income / 12) * 0.25)

    if monthly <= 0:
        return ("概算の試算には「年収」または「毎月のご希望返済額」が必要です。\n"
                "例）年収500万円 / 毎月の返済10万円 / 借入期間35年", False)

    annual_rate = 0.01  # 1%
    r = annual_rate / 12
    n = int(years) * 12

    try:
        principal = int(monthly * (1 - (1 + r) ** (-n)) / r)
    except Exception:
        principal = monthly * n

    income_cap_low = int(income * 6) if income else None
    income_cap_hi  = int(income * 7) if income else None

    lines = []
    lines.append("📊 概算試算（目安）")
    lines.append(f"・想定金利: 約{annual_rate*100:.1f}% / 期間: {years}年")
    lines.append(f"・毎月返済: 約{monthly:,}円")
    if other:
        lines.append(f"・他の毎月負担: 約{other:,}円（参考）")
    lines.append(f"・借入目安（元本）: 約{principal:,}円")

    if income:
        lines.append(f"・年収: 約{income:,}円")
        if income_cap_low and income_cap_hi:
            lines.append(f"・年収倍率の目安: {income_cap_low:,}〜{income_cap_hi:,}円の範囲に収まると安心")

    lines.append("\n※本結果は概算の目安です。詳細は実際の金利/諸費用等で変動します。")
    return ("\n".join(lines), True)

# -------------------------------
# 12) FastAPI ルータ
# -------------------------------
router = APIRouter()

class ChatCompatRequest(BaseModel):
    # 互換: message / question どちらでも可
    message: Optional[str] = None
    question: Optional[str] = None
    session_id: Optional[str] = None
    source: Optional[str] = "web"  # "web" / "line" など

def _extract_message(req: ChatCompatRequest) -> str:
    return (req.message or req.question or "").strip()

@router.post("/chat")
@router.post("/chat/")
@trace_span("unified_chat")
def unified_chat(req: ChatCompatRequest) -> Dict[str, Any]:
    """HTTP 入口（フロント経由）。内部ロジックは generate_response に委譲。"""
    raw = _extract_message(req)
    if not raw:
        raise HTTPException(status_code=400, detail="message is required")

    # まず generate_response を使って統一のレスを得る
    # （generate_response は async だが、内部は I/O を持たないので同期呼び出し互換にしておく）
    resp = _generate_response_sync(raw, req.source or "web")
    resp["elapsed"] = round(resp.get("elapsed", 0.0), 3)
    return resp

# -------------------------------
# 13) main.py から await される正規入口
# -------------------------------
async def generate_response(question: str,
                            platform: str = "web",
                            username: str | None = None,
                            mode: str = "auto") -> Dict[str, Any]:
    """
    正規のエントリーポイント。
    戻り値は main.py の期待形式に合わせる: {answer, sources, source, status}
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
        return {
            "answer": reply,
            "sources": [],
            "source": "richmenu",
            "status": "ok",
            "elapsed": time.time() - t0,
        }

    # b) 「資金計画」系は軽量推定で即答（不足時は次へ）
    if _is_financial_query(raw):
        data = _extract_financial(raw)
        text, ok = _estimate_budget(data)
        if ok:
            return {
                "answer": text,
                "sources": [],
                "source": "finance",
                "status": "ok",
                "elapsed": time.time() - t0,
            }

    # c) RAG を試す（ここで初めてRAGがロードされる）
    with tracer.start_span("RAG.try"):
        rag_text = _rag_answer(raw)
    if rag_text:
        return {
            "answer": rag_text,
            "sources": [],
            "source": "rag",
            "status": "ok",
            "elapsed": time.time() - t0,
        }

    # d) Web検索のヒント（UIフラグ。実検索は別処理）
    try:
        use_web = bool(should_use_web_search(raw))
    except Exception:
        use_web = False

    # e) LLM フォールバック
    with tracer.start_span("LLM.fallback"):
        llm_text = _llm_answer(raw)

    return {
        "answer": llm_text,
        "sources": [],
        "source": "llm",
        "status": "ok",
        "used_web_search": use_web,
        "elapsed": time.time() - t0,
    }

# 内部用（同期互換）―― FastAPI の sync ルートからも使えるように
def _generate_response_sync(question: str, platform: str = "web") -> Dict[str, Any]:
    # 非I/Oなので同期でも安全（内部のRAG/LLM呼び出しが同期実装）
    return _awaitless(generate_response(question, platform))

def _awaitless(coro):
    try:
        # 既存ループがあれば使う（FastAPIのスレッドプール内想定）
        import asyncio
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # running 環境では run_until_complete は不可。I/O無し想定なので簡易return
            return {"answer": "処理中です。", "sources": [], "source": "async", "status": "ok"}
        return loop.run_until_complete(coro)
    except Exception:
        # 最低限のフォールバック
        return {"answer": "ただいま処理が混み合っています。少し時間をおいてお試しください。", "sources": [], "source": "error", "status": "degraded"}

@router.get("/chat/ping")
def ping() -> Dict[str, Any]:
    return {"pong": True}
