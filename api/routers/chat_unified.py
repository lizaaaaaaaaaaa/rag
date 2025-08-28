# api/routers/chat_unified.py
# 統合チャット（固定テンプレ & 出典非表示 & RAG優先 & 資金計画の軽量推定）
from __future__ import annotations

import os
import re
import time
import math
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
    # 既存の util があればそれを使用
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

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# -------------------------------
# 4) web_search（存在しなくてもOK）
# -------------------------------
def _noop_should_use_web_search(_: str) -> bool:  # UI 用のフラグなので未実装でOK
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
# 6) RAG を柔軟にロード
# -------------------------------
_RAG = None
for modname in ("services.rag_chain", "rag.fast_rag_chain", "rag_chain", "fast_rag_chain"):
    try:
        _RAG = importlib.import_module(modname)
        logger.info("RAG module loaded: %s", modname)
        break
    except Exception:
        continue

def _rag_answer(question: str) -> Optional[str]:
    if _RAG is None:
        return None
    try:
        chain = None
        for factory in ("get_ultra_fast_rag_chain", "get_super_fast_rag_chain",
                        "build_fast_rag_chain", "get_rag_chain", "create_rag_chain"):
            fn = getattr(_RAG, factory, None)
            if fn:
                chain = fn()
                break
        if chain is None:
            # 直接関数系
            for direct in ("answer_with_rag", "rag_answer", "answer", "get_rag_response"):
                f = getattr(_RAG, direct, None)
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
# 7) LLM フォールバック（llm_runner → OpenAI → 固定文）
# -------------------------------
def _llm_answer(prompt: str) -> str:
    # 7-1) llm_runner を優先（パッケージ/相対の両対応）
    try:
        try:
            from llm.llm_runner import chat_completion  # type: ignore
        except ModuleNotFoundError:
            from llm.llm_runner import chat_completion  # type: ignore
        return _strip_citations(chat_completion(prompt))
    except Exception as e:
        logger.info("llm_runner fallback to OpenAI: %s", e)

    # 7-2) OpenAI 直
    try:
        import openai  # type: ignore
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set")
        client = openai.OpenAI(api_key=api_key)  # type: ignore[attr-defined]
        rsp = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL_NAME", "gpt-3.5-turbo"),
            messages=[{"role": "user", "content": prompt}],
            temperature=float(os.getenv("OPENAI_TEMPERATURE", "0.1")),
            max_tokens=int(os.getenv("MAX_NEW_TOKENS", "300")),
        )
        return _strip_citations(rsp.choices[0].message.content or "")
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
# 10) リッチメニューの固定テンプレ（ご指定文面）
# -------------------------------
RICHMENU_FIXED_RESPONSES: Dict[str, str] = {
    "follow_greeting": _normalize_colon_emoji("""こんにちは！キノエデザインです。
この度は友だち追加ありがとうございます✨

目的のボタンをタップ👇
🤖AI相談 / 📍来場予約 / 📄資料請求 / 💴資金計画 / 🌐サイト / 💬チャット

AIは24時間、担当者は当日〜翌営業日に返信します。

※ご使用の前に、必ず以下の取り扱いをご確認ください。
プライバシーポリシー：【https://preview.studio.site/live/EjOQljz1WJ/privacy-policy 】
利用規約：【https://preview.studio.site/live/EjOQljz1WJ/termsofuse/service 】
Cookie：【https://preview.studio.site/live/EjOQljz1WJ/cookie 】"""),

    "AI相談": _normalize_colon_emoji("""🤖 AI住まい相談を開始します！
キノエデザインの住まいAIコンシェルジュです。
住まいに関するご質問をお気軽にどうぞ！
💡 **例えば**
・坪単価について教えて
・標準仕様はどんな感じ？
・耐震性能について知りたい
・断熱性能はどのくらい？
何でもお聞きください😊
※ご使用の前に、必ず以下の取り扱いをご確認ください。
プライバシーポリシー：【https://preview.studio.site/live/EjOQljz1WJ/privacy-policy 】
利用規約：【https://preview.studio.site/live/EjOQljz1WJ/termsofuse/service 】
Cookie：【https://preview.studio.site/live/EjOQljz1WJ/cookie 】"""),

    "AI住まいサイト": _normalize_colon_emoji("""🌐 AI住まいサイトのご案内
キノエデザインの住まい情報サイトをご紹介します。（家づくりの疑問にAIが24時間即回答）
🏠 サイト内容：
・AIチャット相談（資金計画／補助金／間取り など）
・施工写真（実例）
・間取りの考え方・プラン例
・よくある質問（最初に迷う3つのこと ほか）
・保存版デジタル冊子 ZINE（無料ダウンロード）
・LINEで無料相談／来場予約
📱 サイトURL:
https://preview.studio.site/live/EjOQljz1WJ/"""),

    "資料請求": _normalize_colon_emoji("""📄ありがとうございます！こちらからご覧いただけます。
〔資料タイトル〕（PDF）：〔URL〕
よろしければ簡単アンケート（任意）：
・ご計画時期：今すぐ / 3–6か月 / 1年以内 / 未定
・連絡方法（任意）：このLINE / メール / 連絡不要
※必ず以下の取り扱いをご確認ください。
プライバシーポリシー：【https://preview.studio.site/live/EjOQljz1WJ/privacy-policy 】
利用規約：【https://preview.studio.site/live/EjOQljz1WJ/termsofuse/service 】
Cookie：【https://preview.studio.site/live/EjOQljz1WJ/cookie 】"""),

    "展示場来場予約": _normalize_colon_emoji("""📍 展示場のご来場予約につきましては、下記URLより必要事項のご入力をお願い申し上げます。
【https://preview.studio.site/live/EjOQljz1WJ/reservation 】
スタッフ一同、心よりお待ちしております！"""),

    "資金計画": _normalize_colon_emoji("""💴 AI資金診断のご案内
本診断は匿名でご利用いただけます。ご回答内容は保存いたしません。算出される金額は試算（概算）であり、目安としてご確認ください。
お手数ですが、以下の5点をご入力ください。
・年収（概算可）
・毎月のご希望返済額
・住宅ローンのご希望借入期間
・ご家族構成（例：大人2名・お子さま1名）
・その他の大きなご負担（例：自動車ローン 等）
未入力の項目があっても進められます。ご入力後、概算結果をご提示いたします。"""),

    "チャット相談": _normalize_colon_emoji("""💬 スタッフとのご相談
【対応時間】
営業時間：9:00-18:00
📱 ご相談方法：
・このLINEでの直接相談
・お電話での相談
・展示場での対面相談
営業時間内でしたら迅速にお返事します。
お気軽にお声かけください！"""),
}

# 押下ゆらぎ吸収（コロン表記/全角スペース/別名）
RICHMENU_KEYWORD_MAPPING: Dict[str, str] = {
    # AI相談
    "AI相談": "AI相談", ":robot: AI相談": "AI相談", "🤖 AI相談": "AI相談",
    # AI住まいサイト
    "AI住まいサイト": "AI住まいサイト", "🌐 AI住まいサイト": "AI住まいサイト",
    "サイト": "AI住まいサイト", "ホームページ": "AI住まいサイト",
    # 資料請求
    "資料請求": "資料請求", "📄 資料請求": "資料請求", ":page_facing_up: 資料請求": "資料請求",
    # 展示場来場予約（全角スペース対応）
    "展示場来場予約": "展示場来場予約", "📍 展示場来場　予約": "展示場来場予約",
    "来場予約": "展示場来場予約", ":round_pushpin: 展示場来場　予約": "展示場来場予約",
    # 資金計画
    "資金計画": "資金計画", "💴 資金計画": "資金計画", "💰 資金計画": "資金計画",
    ":moneybag: 資金計画": "資金計画",
    # チャット相談
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
    # 「AI相談」「資金計画」など単語だけ来た場合にも拾う
    if msg in RICHMENU_KEYWORD_MAPPING:
        return RICHMENU_KEYWORD_MAPPING[msg]
    return None

# -------------------------------
# 11) 資金計画の最軽量推定（ユーザー入力をざっくり解析）
# -------------------------------
def _parse_money(s: str) -> Optional[int]:
    # 500万円 / 50万 / 100,000円 / 10万5千 など
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
        "annual_income": None,      # 年収（円）
        "monthly_payment": None,    # 希望毎月返済（円）
        "years": None,              # 借入年数（年）
        "family": None,             # 家族構成（文字列）
        "other_debt": None          # 他負担（円）
    }
    # 年収
    m = re.search(r"(年収)\s*[:：]?\s*([0-9,\.万千円]+)", text)
    if m: data["annual_income"] = _parse_money(m.group(2))
    # 毎月返済
    m = re.search(r"(毎月.*返済額|月.*返済)\s*[:：]?\s*([0-9,\.万千円]+)", text)
    if m: data["monthly_payment"] = _parse_money(m.group(2))
    # 借入期間
    m = re.search(r"(借入|期間|年数)\s*[:：]?\s*(\d+)\s*年", text)
    if m: data["years"] = int(m.group(2))
    # 家族構成
    m = re.search(r"(家族構成)\s*[:：]?\s*(.+)", text)
    if m: data["family"] = m.group(2).strip()
    # 他負担
    m = re.search(r"(負担|ローン)\s*[:：]?\s*([0-9,\.万千円]+)", text)
    if m: data["other_debt"] = _parse_money(m.group(2))
    return data

def _is_financial_query(message: str) -> bool:
    keys = ("年収", "返済", "借入", "家族構成", "ローン")
    return any(k in message for k in keys)

def _estimate_budget(data: Dict[str, Optional[int | str]]) -> Tuple[str, bool]:
    """返済能力の超簡易試算（超軽量・状態レス）"""
    income = data.get("annual_income") or 0
    monthly = data.get("monthly_payment") or 0
    years = data.get("years") or 35  # 未指定なら35年
    other = data.get("other_debt") or 0

    # 希望月返済がなければ年収から目安（返済比率25%仮置き）
    if not monthly and income:
        monthly = int((income / 12) * 0.25)

    if monthly <= 0:
        return ("概算の試算には「年収」または「毎月のご希望返済額」が必要です。\n"
                "例）年収500万円 / 毎月の返済10万円 / 借入期間35年", False)

    # 年利（固定の仮定・実務では外出し推奨）
    annual_rate = 0.01  # 1%
    r = annual_rate / 12
    n = int(years) * 12

    try:
        # 返済額から元本Pを逆算: P = M * (1 - (1+r)^-n) / r
        principal = int(monthly * (1 - (1 + r) ** (-n)) / r)
    except Exception:
        principal = monthly * n  # 金利0近似

    # 年収からの安全レンジ（年収の6〜7倍に収まるかの簡易目安）
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

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    source: Optional[str] = "web"  # "web" / "line" など

@router.post("/chat")
@trace_span("unified_chat")
def unified_chat(req: ChatRequest) -> Dict[str, Any]:
    t0 = time.time()
    raw = (req.message or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="message is required")

    # a) リッチメニュー（押下文面）は即時返答（高速・非同期不要）
    pressed = None
    try:
        pressed = is_richmenu_pressed(raw)  # 外部 util があれば
    except Exception:
        pressed = None
    if not pressed:
        pressed = _detect_richmenu_press(raw)

    if pressed:
        # 定型文（絵文字対応済）
        reply = RICHMENU_FIXED_RESPONSES.get(pressed, "")
        return {
            "ok": True,
            "mode": "richmenu",
            "answer": reply,
            "elapsed": round(time.time() - t0, 3),
        }

    # b) 「資金計画」系の入力フォーマットだったら、軽量推定を即返答
    if _is_financial_query(raw):
        data = _extract_financial(raw)
        text, ok = _estimate_budget(data)
        if ok:
            return {
                "ok": True,
                "mode": "finance",
                "answer": text,
                "elapsed": round(time.time() - t0, 3),
            }
        # 必要項目不足なら、RAG/LLM に続行

    # c) まず RAG（成功すれば終了）
    with tracer.start_span("RAG.try"):
        rag_text = _rag_answer(raw)
    if rag_text:
        return {
            "ok": True,
            "mode": "rag",
            "answer": rag_text,
            "elapsed": round(time.time() - t0, 3),
        }

    # d) Web 検索フラグ（UI補助。実際の検索は別途）
    try:
        use_web = bool(should_use_web_search(raw))
    except Exception:
        use_web = False

    # e) LLM フォールバック
    with tracer.start_span("LLM.fallback"):
        llm_text = _llm_answer(raw)

    return {
        "ok": True,
        "mode": "llm",
        "used_web_search": use_web,
        "answer": llm_text,
        "elapsed": round(time.time() - t0, 3),
    }

@router.get("/chat/ping")
def ping() -> Dict[str, Any]:
    return {"pong": True}
