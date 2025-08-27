# api/routers/chat_unified.py — 統合チャット（固定テンプレ & 出典非表示 & RAG優先）
# - リッチメニュー押下テキストを検知 → 指定の固定文面を即返答
# - それ以外は RAG を優先し、失敗時のみ LLM フォールバック
# - すべての最終応答から「出典/参考/資料」系の行を除去

from __future__ import annotations
import os
import re
import time
import logging
from typing import Optional, Dict, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ========= フォールバック import（どの配置でも落ちない） =========
# web_search（任意）
try:
    # 通常: utils/web_search.py がある構成
    from utils.web_search import should_use_web_search, is_richmenu_pressed
except ModuleNotFoundError:
    # 直下: web_search.py がリポジトリ直下にある構成
    from web_search import should_use_web_search, is_richmenu_pressed
except Exception as e:  # 万一のため
    logger.warning("web_search import fallback failed: %s", e)

    def should_use_web_search(_: str) -> bool:
        return False

    def is_richmenu_pressed(_: str) -> Optional[str]:
        return None

# tracer（LangSmith が無い/無効でも動くように）
try:
    try:
        from utils.langsmith_tracer import trace_span, RAGTracer
    except ModuleNotFoundError:
        from langsmith_tracer import trace_span, RAGTracer  # 直下版
except Exception:
    # ない場合はダミー（完全ノーオプ）
    def trace_span(_name: str):
        def deco(fn):
            return fn
        return deco

    class RAGTracer:  # type: ignore
        def start_span(self, *_a, **_k):
            class _CM:
                def __enter__(self): return self
                def __exit__(self, *exc): return False
            return _CM()
        def record(self, *_a, **_k): pass

tracer = RAGTracer()

# ========= RAG 呼び出し（services/ rag/ 直下 どれでも拾う） =========
_rag_mod = None
for _name in ("services.rag_chain", "rag.fast_rag_chain", "rag_chain", "fast_rag_chain"):
    try:
        import importlib
        _rag_mod = importlib.import_module(_name)
        logger.info("RAG module loaded: %s", _name)
        break
    except Exception:
        continue

def _call_rag(question: str, session_id: Optional[str] = None) -> Optional[str]:
    """RAG 実行を“ゆるく”ラップ。モジュールごとの関数名差異に対応。"""
    if _rag_mod is None:
        return None
    try:
        # 代表的なファクトリ名を順に試す
        chain = None
        for factory in (
            "get_ultra_fast_rag_chain",
            "get_super_fast_rag_chain",
            "build_fast_rag_chain",
            "get_rag_chain",
            "create_rag_chain",
        ):
            chain_factory = getattr(_rag_mod, factory, None)
            if chain_factory:
                chain = chain_factory()  # type: ignore[call-arg]
                break
        if chain is None:
            # 直接 answer/qa 関数がある場合
            for direct in ("answer_with_rag", "rag_answer", "answer", "get_rag_response"):
                f = getattr(_rag_mod, direct, None)
                if f:
                    out = f(question)  # type: ignore[misc]
                    if isinstance(out, tuple):  # (answer, meta) 形式ケア
                        out = out[0]
                    return _strip_citations(_as_text(out))
            return None

        # LangChain 互換（invoke / __call__ / run）を順に試す
        payload = {"question": question, "query": question, "input": question}
        if hasattr(chain, "invoke"):
            out = chain.invoke(payload)  # type: ignore[attr-defined]
        elif callable(chain):
            out = chain(payload)
        elif hasattr(chain, "run"):
            out = chain.run(question)  # type: ignore[attr-defined]
        else:
            return None
        return _strip_citations(_as_text(out))
    except Exception as e:
        logger.exception("RAG execution failed: %s", e)
        return None

def _as_text(out: Any) -> str:
    if isinstance(out, str):
        return out
    if isinstance(out, dict):
        for k in ("answer", "output", "result", "text", "final"):
            if k in out and isinstance(out[k], str):
                return out[k]
    return str(out)

# ========= LLM 直叩き（llm_runner 優先 → OpenAI → 簡易文） =========
def _call_llm(prompt: str) -> str:
    # 1) llm_runner（推奨）
    try:
        try:
            from llm.llm_runner import chat_completion  # パッケージ版
        except ModuleNotFoundError:
            from llm.llm_runner import chat_completion  # 直下版
        return _strip_citations(chat_completion(prompt))
    except Exception:
        pass

    # 2) OpenAI 直接（openai>=1.x を想定、キーが未設定ならスキップ）
    try:
        import openai  # type: ignore[import-not-found]
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set")
        client = openai.OpenAI(api_key=api_key)  # type: ignore[attr-defined]
        rsp = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL_NAME", "gpt-3.5-turbo"),
            messages=[{"role": "user", "content": prompt}],
            temperature=float(os.getenv("OPENAI_TEMPERATURE", "0.1")),
            max_tokens=int(os.getenv("MAX_NEW_TOKENS", "300")),
            stream=False,
        )
        return _strip_citations(rsp.choices[0].message.content or "（応答が空でした）")
    except Exception as e:
        logger.warning("OpenAI fallback not available: %s", e)

    # 3) 最終手段
    return "今のご質問について準備中です。もう一度お試しください。"

# ========= 「出典/参考/資料」等の非表示フィルタ =========
def _strip_citations(text: str) -> str:
    if not text:
        return text
    text = re.sub(r"^\s*(参考|資料|出典)\s*[:：].*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"【出典】[\s\S]*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s*\(p\.\s*\d+\s*\)\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text

# ========= リッチメニュー固定テンプレ（ご指定文面に完全一致） =========
RICHMENU_FIXED_RESPONSES: Dict[str, str] = {
    # 友だち追加後（Web 側でも同文面で案内）
    "follow_greeting": """こんにちは！キノエデザインです。
この度は友だち追加ありがとうございます:sparkles:

目的のボタンをタップ:point_down:
:robot:AI相談 / :round_pushpin:来場予約 / :page_facing_up:資料請求 / :yen:資金計画 / :globe_with_meridians:サイト / :speech_balloon:チャット

AIは24時間、担当者は当日〜翌営業日に返信します。

※ご使用の前に、必ず以下の取り扱いをご確認ください。
プライバシーポリシー：【https://preview.studio.site/live/EjOQljz1WJ/privacy-policy 】
利用規約：【https://preview.studio.site/live/EjOQljz1WJ/termsofuse/service 】
Cookie：【https://preview.studio.site/live/EjOQljz1WJ/cookie 】""",

    # AI相談
    "AI相談": """:robot: AI住まい相談を開始します！
キノエデザインの住まいAIコンシェルジュです。
住まいに関するご質問をお気軽にどうぞ！
:bulb: **例えば**
・坪単価について教えて
・標準仕様はどんな感じ？
・耐震性能について知りたい
・断熱性能はどのくらい？
何でもお聞きください:blush:
※ご使用の前に、必ず以下の取り扱いをご確認ください。
プライバシーポリシー：【https://preview.studio.site/live/EjOQljz1WJ/privacy-policy 】
利用規約：【https://preview.studio.site/live/EjOQljz1WJ/termsofuse/service 】
Cookie：【https://preview.studio.site/live/EjOQljz1WJ/cookie 】""",

    # AI住まいサイト
    "AI住まいサイト": """:globe_with_meridians: AI住まいサイトのご案内
キノエデザインの住まい情報サイトをご紹介します。（家づくりの疑問にAIが24時間即回答）
:house: サイト内容：
・AIチャット相談（資金計画／補助金／間取り など）
・施工写真（実例）
・間取りの考え方・プラン例
・よくある質問（最初に迷う3つのこと ほか）
・保存版デジタル冊子 ZINE（無料ダウンロード）
・LINEで無料相談／来場予約
:mobile_phone: サイトURL:
https://preview.studio.site/live/EjOQljz1WJ/""",

    # 資料請求
    "資料請求": """:clipboard:ありがとうございます！こちらからご覧いただけます。
〔資料タイトル〕（PDF）：〔URL〕
よろしければ簡単アンケート（任意）：
・ご計画時期：今すぐ / 3–6か月 / 1年以内 / 未定
・連絡方法（任意）：このLINE / メール / 連絡不要
※必ず以下の取り扱いをご確認ください。
プライバシーポリシー：【https://preview.studio.site/live/EjOQljz1WJ/privacy-policy 】
利用規約：【https://preview.studio.site/live/EjOQljz1WJ/termsofuse/service 】
Cookie：【https://preview.studio.site/live/EjOQljz1WJ/cookie 】""",

    # 展示場来場予約
    "展示場来場予約": """:round_pushpin: 展示場のご来場予約につきましては、下記URLより必要事項のご入力をお願い申し上げます。
【https://preview.studio.site/live/EjOQljz1WJ/reservation 】
スタッフ一同、心よりお待ちしております！""",

    # 資金計画
    "資金計画": """:speech_balloon: AI資金診断のご案内
本診断は匿名でご利用いただけます。ご回答内容は保存いたしません。算出される金額は試算（概算）であり、目安としてご確認ください。
お手数ですが、以下の5点をご入力ください。
・年収（概算可）
・毎月のご希望返済額
・住宅ローンのご希望借入期間
・ご家族構成（例：大人2名・お子さま1名）
・その他の大きなご負担（例：自動車ローン 等）
未入力の項目があっても進められます。ご入力後、概算結果をご提示いたします。""",

    # チャット相談
    "チャット相談": """:speech_balloon: スタッフとのご相談
【対応時間】
営業時間：9:00-18:00
:mobile_phone: ご相談方法：
・このLINEでの直接相談
・お電話での相談
・展示場での対面相談
営業時間内でしたら迅速にお返事します。
お気軽にお声かけください！""",
}

# ボタン文言のゆらぎを吸収
RICHMENU_KEYWORD_MAPPING: Dict[str, str] = {
    # AI相談
    "AI相談": "AI相談",
    ":robot: AI相談": "AI相談",
    "🤖 AI相談": "AI相談",
    # AI住まいサイト
    "AI住まいサイト": "AI住まいサイト",
    ":globe_with_meridians: AI住まいサイト": "AI住まいサイト",
    "サイト": "AI住まいサイト",
    "ホームページ": "AI住まいサイト",
    # 資料請求
    "資料請求": "資料請求",
    ":clipboard: 資料請求": "資料請求",
    # 展示場来場予約
    "展示場来場予約": "展示場来場予約",
    ":round_pushpin: 展示場来場　予約": "展示場来場予約",
    "来場予約": "展示場来場予約",
    # 資金計画
    "資金計画": "資金計画",
    ":moneybag: 資金計画": "資金計画",
    "💰 資金計画": "資金計画",
    # チャット相談
    "チャット相談": "チャット相談",
    ":speech_balloon: チャット相談": "チャット相談",
    "チャット": "チャット相談",
}

def detect_richmenu_press(msg: str) -> Optional[str]:
    """外部の is_richmenu_pressed が無い/None の場合に、こちらで検出"""
    if not msg:
        return None
    msg = msg.strip()
    if msg in RICHMENU_FIXED_RESPONSES:
        return msg
    for k, mapped in RICHMENU_KEYWORD_MAPPING.items():
        if k in msg:
            return mapped
    return None

# ========= FastAPI Router =========

router = APIRouter()

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    source: Optional[str] = "web"  # "web" / "line" など

@router.post("/chat")
@trace_span("unified_chat")
def unified_chat(req: ChatRequest) -> Dict[str, Any]:
    t0 = time.time()
    msg = (req.message or "").strip()
    if not msg:
        raise HTTPException(status_code=400, detail="message is required")

    # 1) リッチメニュー押下時は定型文を即返し（RAGは次の発話から）
    pressed = None
    try:
        pressed = is_richmenu_pressed(msg)  # type: ignore[misc]
    except Exception:
        pressed = None
    if not pressed:
        pressed = detect_richmenu_press(msg)
    if pressed:
        reply = RICHMENU_FIXED_RESPONSES.get(pressed, "")
        logger.info("Richmenu pressed: %s", pressed)
        return {
            "ok": True,
            "mode": "richmenu",
            "elapsed": round(time.time() - t0, 3),
            "answer": reply,
        }

    # 2) まず RAG を試す（成功すればそこで終了）— 出典カット
    with tracer.start_span("RAG.try"):
        rag_text = _call_rag(msg, req.session_id)
    if rag_text:
        return {
            "ok": True,
            "mode": "rag",
            "elapsed": round(time.time() - t0, 3),
            "answer": rag_text,
        }

    # 3) Web 検索フラグ（フロント側表示制御用。使わないなら無視OK）
    use_web = False
    try:
        use_web = bool(should_use_web_search(msg))
    except Exception:
        use_web = False

    # 4) LLM 直叩き（最終フォールバック）— 出典カット
    with tracer.start_span("LLM.fallback"):
        llm_text = _call_llm(msg)

    return {
        "ok": True,
        "mode": "llm" if not rag_text else "rag",
        "used_web_search": bool(use_web),
        "elapsed": round(time.time() - t0, 3),
        "answer": llm_text,
    }

# 動作確認
@router.get("/chat/ping")
def ping() -> Dict[str, Any]:
    return {"pong": True}
