# api/routers/line_bot_ultra_fast.py (FULL FIXED VERSION)
# - Webhook path unified to "/webhook" (use include_router(..., prefix="/line") in main.py)
# - Keep all fixed texts as-is; only order + emoji handling + normalization + exact-match mapping
# - Add "友だちに紹介" (share) support via LIFF (LIFF_SHARE_URL or LIFF_ID_SHARE)
# - Fallback list order: 🤖 / 🌐 / 📋 / 📍 / 🧑‍🤝‍🧑 / 💬
# - No sentence content changes other than replacing colon-emoji with real emoji for display stability

import logging, os, re, time, hashlib, threading, sys, pathlib, importlib, json, traceback
from datetime import datetime
from typing import Dict, Optional, Any, Tuple
from urllib.parse import urlencode, urlparse, parse_qsl, urlunparse
from uuid import uuid4

from fastapi import APIRouter, Request, BackgroundTasks, Body, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# -------------------------------
# UTM helper (fallback if line_utils not present)
# -------------------------------
def _with_utm_fallback(url: str, source: str, ab: str | None = None) -> str:
    u = urlparse(url)
    q = dict(parse_qsl(u.query))
    q.setdefault("utm_source", "line")
    q.setdefault("utm_medium", "richmenu")
    q["utm_campaign"] = source
    if ab:
        q["ab"] = ab
    return urlunparse((u.scheme, u.netloc, u.path, u.params, urlencode(q), u.fragment))

try:
    from api.routers.line_utils import with_utm  # type: ignore
except Exception:
    with_utm = _with_utm_fallback  # type: ignore

logger = logging.getLogger(__name__)

# ======================================================================
# Lazy import for RAG / financial (kept for backward compat)
# ======================================================================
ROOT = pathlib.Path(__file__).resolve().parents[2]  # .../RAG-LLM-Project
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_get_rag_response = None
def _resolve_rag_if_needed():
    global _get_rag_response
    if _get_rag_response:
        return _get_rag_response
    for cand in ("api.services.rag_chain", "services.rag_chain", "rag.rag_chain", "rag_chain"):
        try:
            mod = importlib.import_module(cand)
            _get_rag_response = getattr(mod, "get_rag_response", None)
            if _get_rag_response:
                logger.info(f"RAG module resolved via: {cand}")
                break
        except Exception:
            continue
    return _get_rag_response

_run_financial_plan = None
def _resolve_financial_if_needed():
    global _run_financial_plan
    if _run_financial_plan:
        return _run_financial_plan
    for cand in ("api.routers.line_bot_financial_planner", "line_bot_financial_planner",
                 "api.routers.financial_api", "financial_api", "services.financial_api"):
        try:
            mod = importlib.import_module(cand)
            _run_financial_plan = getattr(mod, "run_financial_plan", None)
            if _run_financial_plan:
                logger.info(f"Financial module resolved via: {cand}")
                break
        except Exception:
            continue
    return _run_financial_plan

# ======================================================================
# Strip citations / placeholders (unchanged behavior)
# ======================================================================
def _strip_citations(text: str) -> str:
    if not text:
        return text
    text = re.sub(r"(?m)^\\s*(参考|参考資料|参考文献|資料|出典|引用)\\s*[:：].*$", "", text)
    text = re.sub(r"(参考|参考資料|資料|出典|引用)\\s*[:：].*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"【\\s*(出典|参考|資料)\\s*】[\\s\\S]*?$", "", text, flags=re.MULTILINE)
    text = re.sub(r"[（(]\\s*[pP]\\s*[\\.:：]?\\s*(\\d+|[?？]+)\\s*[)）]", "", text)
    text = re.sub(r"\\n{3,}", "\\n\\n", text).strip()
    return text

_PLACEHOLDER_RE = re.compile(r"(○○|〇〇|××|X{2,}|XXXX|TBD|未定|要確認|？？？|\\?{2,}|＜.*?＞|ここに.*?を書く)")

def _strip_placeholders(t: str) -> str:
    if not t:
        return t
    tt = _PLACEHOLDER_RE.sub("（資料に記載なし）", t)
    if "（資料に記載なし）" in tt and len(tt) < 40:
        return "資料内に該当情報が見つかりませんでした。必要であれば担当へ確認します。"
    return tt

def _finalize_text(t: str) -> str:
    return _strip_placeholders(_strip_citations(t or "")).strip()

# ======================================================================
# LINE SDK v3
# ======================================================================
try:
    from linebot.v3 import WebhookHandler
    from linebot.v3.messaging import (
        Configuration, ApiClient, MessagingApi,
        ReplyMessageRequest, PushMessageRequest, TextMessage, ApiException,
        FlexMessage, FlexBubble, FlexBox, FlexText, FlexButton, FlexSeparator,
        URIAction
    )
    from linebot.v3.webhooks import MessageEvent, TextMessageContent, PostbackEvent, FollowEvent
    LINE_SDK_AVAILABLE = True
    FLEX_AVAILABLE = True
    logger.info("✅ LINE Bot SDK v3 with Flex imported")
except Exception as e:
    LINE_SDK_AVAILABLE = False
    FLEX_AVAILABLE = False
    logger.error(f"❌ LINE Bot SDK import failed: {e}")
    class WebhookHandler:  # dummy
        def __init__(self,*a,**k): ...
        def add(self,*a,**k):
            def deco(f): return f
            return deco
        def handle(self,*a,**k): ...

# ======================================================================
# Router
# ======================================================================
router = APIRouter(prefix="", tags=["line-ultra-fast"])

# ======================================================================
# Config
# ======================================================================
LINE_RESPONSE_TIMEOUT = int(os.getenv("LINE_RESPONSE_TIMEOUT", "12"))
SESSION_TTL = int(os.getenv("SESSION_TTL_MINUTES", "30")) * 60

PUBLIC_BASE_URL = (os.getenv("PUBLIC_BASE_URL") or os.getenv("PUBLIC_API_BASE") or "").rstrip("/")
if not PUBLIC_BASE_URL:
    logger.warning("PUBLIC_BASE_URL is not set.")

LIFF_CONSENT_URL = os.getenv("LIFF_CONSENT_URL", "").rstrip("/")
LIFF_SHARE_URL = os.getenv("LIFF_SHARE_URL", "").rstrip("/")
LIFF_ID_SHARE = os.getenv("LIFF_ID_SHARE", "").strip()

# ======================================================================
# Fixed texts (unchanged sentences; only emoji are real Unicode)
# ======================================================================
RICHMENU_FIXED_RESPONSES: Dict[str, str] = {
    "follow_greeting": """こんにちは！キノエデザイン住まいAIプランナーです。
この度は友だち追加ありがとうございます✨
このAIは住宅検討の参考用に設計された自動応答です。
最終的な、ご提案はスタッフが行います。
また、AIに個人情報は入力しないでください。
📸💪 キノエデザインの設計思想とAI技術が、理想の住まいづくりを完全サポート！
📱💬まずはリッチメニューから気になる項目をタップ
または、直接メッセージでご質問ください。
📍 各展示場でも実際にご相談いただけます""",

    "🤖 AI相談": """🤖 AI住まい相談を開始します！
キノエデザインの住まいAIプランナーです。
住まいに関するご質問をお気軽にどうぞ！
💡 例えば
・坪単価について教えて
・標準仕様はどんな感じ？
・耐震性能について知りたい
・断熱性能はどのくらい？
何でもお聞きください😊

※AIに個人情報は入力しないでください。
※このAIは住宅検討の参考用に設計された自動応答です。
※AIの回答は必ずしも正しいとは限りません。→ 確定案内はスタッフが行います。
※ご質問の内容により、AIの回答までお時間を頂戴する場合がございます。
※ご使用の前に、必ず同意が必要となります。何卒ご理解賜りますようお願い申し上げます。""",

    "AI住まいサイト": """🌐 住まいAIサイトのご案内
キノエデザインの住まいAI情報サイトをご紹介します。（家づくりの疑問にAIが24時間即回答）
🏠気になることや、お悩みをAIが、お答え・解決するホームページです。
ZINE、ダウンロードもできます。
※ AIに個人情報は入力しないでください／保存OFF（既定）
※ このAIは住宅検討の参考用に設計された自動応答です。
※ AIの回答は必ずしも正しいとは限りません。→ 確定案内はスタッフが行います。
※ ご質問の内容により、AIの回答までお時間を頂戴する場合がございます。
※ ご使用の前に、必ず同意が必要となります。何卒ご理解賜りますようお願い申し上げます。
📱 サイトURL：
https://ai.kinoedesign.co.jp/""",

    "資料請求": """📋ありがとうございます！
下記のリンクより、資料をご請求ください。
リンク：https://kinoedesign.co.jp/request/""",

    "展示場来場予約": """📍 展示場のご来場予約:
24 時間いつでも、予約OKです。
ご予約の際は、下記の来場予約ホームページURLよりご送信ください。
来場予約ホームページURL：
【https://kinoedesign.co.jp/consultation/ 】""",

    "チャット相談": """💬 スタッフとのご相談
AIより、人の方がお好みの方はこちら。
スタッフとチャット相談。
お気軽にメッセージどうぞ！
【対応時間】
営業時間：9:00-18:00
📱 ご相談方法：
・このLINEでの直接チャット相談
・お電話での相談 0794-82-8540
・展示場での対面相談 https://kinoedesign.co.jp/consultation/
・メールでのお問い合わせ https://kinoedesign.co.jp/contact/
お気軽にお声かけください！""",
}

# ======================================================================
# Share (友だちに紹介) URL resolver
# ======================================================================
def _resolve_share_url() -> Optional[str]:
    if LIFF_SHARE_URL:
        return with_utm(LIFF_SHARE_URL, "share_friends")
    if LIFF_ID_SHARE:
        return f"https://liff.line.me/{LIFF_ID_SHARE}"
    # fallback to static path under public base (if provided)
    if PUBLIC_BASE_URL:
        return with_utm(f"{PUBLIC_BASE_URL}/web/liff/share.html", "share_friends")
    return None

# ======================================================================
# Mapping and normalization
# ======================================================================
# Canonical keys
K_AI = "🤖 AI相談"
K_SITE = "AI住まいサイト"
K_DOC = "資料請求"
K_RESERVE = "展示場来場予約"
K_SHARE = "友だちに紹介"
K_CHAT = "チャット相談"

# Visible order for fallback guidance
FALLBACK_ORDER = "🤖 AI相談 / 🌐 AI住まいサイト / 📋 資料請求 / 📍 来場予約 / 🧑‍🤝‍🧑友達に紹介 / 💬 チャット相談"

def _normalize_button_text(t: str) -> str:
    t = (t or "").strip()
    # unify spaces
    t = re.sub(r"\\s+", " ", t)
    # normalize 友達/友だち
    t = t.replace("友達", "友だち")
    return t

RICHMENU_KEYWORD_MAPPING: Dict[str, str] = {
    # exact visible labels
    "🤖 AI相談": K_AI,
    "🌐 AI住まいサイト": K_SITE,
    "📋 資料請求": K_DOC,
    "📍 来場予約": K_RESERVE,
    "🧑‍🤝‍🧑友だちに紹介": K_SHARE,
    "💬 チャット相談": K_CHAT,
    # emoji-less fallbacks
    "AI相談": K_AI,
    "AI住まいサイト": K_SITE,
    "資料請求": K_DOC,
    "来場予約": K_RESERVE,
    "友だちに紹介": K_SHARE,
    "チャット相談": K_CHAT,
    # minor synonyms
    "サイト": K_SITE,
    "ホームページ": K_SITE,
}

# ======================================================================
# Sessions / duplicate guard
# ======================================================================
class SessionManager:
    def __init__(self):
        self._modes: Dict[str, Tuple[str, float]] = {}

    def get_mode(self, user_id: str) -> Optional[str]:
        rec = self._modes.get(user_id)
        if not rec: return None
        mode, ts = rec
        if (time.time() - ts) > SESSION_TTL:
            del self._modes[user_id]
            return None
        return mode

    def set_mode(self, user_id: str, mode: str):
        self._modes[user_id] = (mode, time.time())

sessions = SessionManager()

class DuplicateGuard:
    def __init__(self, ttl: int = 15):
        self._seen: Dict[str, float] = {}
        self._ttl = ttl

    def seen(self, user_id: str, key: str) -> bool:
        now = time.time()
        full_key = f"{user_id}:{key}"
        expired = [k for k, ts in self._seen.items() if (now - ts) > self._ttl]
        for k in expired: del self._seen[k]
        if full_key in self._seen: return True
        self._seen[full_key] = now
        return False

dup_guard = DuplicateGuard(ttl=15)

# ======================================================================
# LINE initialization
# ======================================================================
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
LINE_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")

_api_instance = None
def _ensure_api():
    global _api_instance
    if not LINE_SDK_AVAILABLE: return None
    if _api_instance: return _api_instance
    if not LINE_ACCESS_TOKEN:
        logger.error("LINE_ACCESS_TOKEN not set")
        return None
    try:
        config = Configuration(access_token=LINE_ACCESS_TOKEN)
        client = ApiClient(configuration=config)
        _api_instance = MessagingApi(api_client=client)
        logger.info("LINE MessagingApi initialized")
        return _api_instance
    except Exception as e:
        logger.error(f"API initialization failed: {e}")
        return None

handler = None
if LINE_SDK_AVAILABLE and LINE_CHANNEL_SECRET:
    handler = WebhookHandler(channel_secret=LINE_CHANNEL_SECRET)
    logger.info("✅ LINE WebhookHandler created")
else:
    logger.warning("❌ No LINE WebhookHandler (SDK or secret missing)")

# ======================================================================
# Consent helpers
# ======================================================================
def _make_user_token(user_id: str) -> str:
    secret = os.getenv("SESSION_SECRET", "kinoe-ai-session")
    data = f"{user_id}:{time.time()}"
    h = hashlib.sha256((data + secret).encode()).hexdigest()
    return f"{user_id}.{h[:16]}"

def _make_consent_link(user_id: str) -> str:
    token = _make_user_token(user_id)
    if LIFF_CONSENT_URL:
        sep = "&" if "?" in LIFF_CONSENT_URL else "?"
        return f"{LIFF_CONSENT_URL}{sep}user_token={token}"
    else:
        return f"{PUBLIC_BASE_URL}/line-consent?user_token={token}"

def _not_consent_msg_for(user_id: str) -> str:
    link = _make_consent_link(user_id)
    return ("🔔 AI相談を利用するには、最初に同意が必要です。\\n\\n"
            f"こちらから同意をお願いします：\\n{link}")

def _is_line_uid(s: str) -> bool:
    return bool(s and s.startswith("U") and len(s) > 20)

def _extract_user_id_from_token(token: str) -> str:
    if not token: return ""
    parts = token.split(".")
    if parts and _is_line_uid(parts[0]): return parts[0]
    return ""

def _has_consent_sync(user_id: str) -> bool:
    return True

# ======================================================================
# Reply/Push helpers
# ======================================================================
def _reply_or_push(reply_token: Optional[str], user_id: str, text: str) -> bool:
    api = _ensure_api()
    if not api or not user_id: return False
    text = _finalize_text(text) or "（エラー）"
    try:
        if reply_token:
            msg = TextMessage(text=text)
            api.reply_message(ReplyMessageRequest(reply_token=reply_token, messages=[msg]))
            logger.info(f"replied to {user_id[:8]}...")
        else:
            _push(user_id, text)
        return True
    except ApiException as e:
        logger.error(f"reply/push error: {e}")
        return False

def _push(user_id: str, text: str) -> bool:
    api = _ensure_api()
    if not api or not user_id: return False
    text = _finalize_text(text) or "（エラー）"
    try:
        msg = TextMessage(text=text)
        api.push_message(PushMessageRequest(to=user_id, messages=[msg]))
        logger.info(f"pushed to {user_id[:8]}...")
        return True
    except ApiException as e:
        logger.error(f"push error: {e}")
        return False

def _reply_or_push_flex(reply_token: Optional[str], user_id: str, flex_msg: FlexMessage) -> bool:
    api = _ensure_api()
    if not api or not user_id: return False
    try:
        if reply_token:
            api.reply_message(ReplyMessageRequest(reply_token=reply_token, messages=[flex_msg]))
            logger.info(f"flex replied to {user_id[:8]}...")
        else:
            api.push_message(PushMessageRequest(to=user_id, messages=[flex_msg]))
            logger.info(f"flex pushed to {user_id[:8]}...")
        return True
    except ApiException as e:
        logger.error(f"flex send error: {e}")
        return False

# ======================================================================
# Flex message for consent
# ======================================================================
def build_consent_flex(liff_url: str) -> FlexMessage:
    if not FLEX_AVAILABLE:
        raise RuntimeError("FlexMessage not available")

    bubble = FlexBubble(
        body=FlexBox(
            layout="vertical",
            spacing="md",
            contents=[
                FlexText(text="🤖 AI相談", weight="bold", size="lg"),
                FlexText(
                    text="以下を確認のうえ「同意して開始」を押してください。",
                    wrap=True,
                    size="sm",
                    color="#555555"
                ),
                FlexSeparator(),
                FlexText(
                    text="・AIに個人情報は入力しないでください\\n・AIの回答は必ずしも正しいとは限りません\\n・最終案内はスタッフが行います",
                    wrap=True,
                    size="xs",
                    color="#666666"
                )
            ]
        ),
        footer=FlexBox(
            layout="vertical",
            spacing="sm",
            contents=[
                FlexButton(
                    style="primary",
                    color="#17c950",
                    action=URIAction(label="同意して開始", uri=liff_url)
                )
            ]
        )
    )
    return FlexMessage(alt_text="AI相談の同意をお願いします", contents=bubble)

# ======================================================================
# Workers
# ======================================================================
def _worker_finance(user_id: str, text: str):
    try:
        fn = _resolve_financial_if_needed()
        if not fn:
            _push(user_id, "資金計画機能が利用できません。")
            return
        res = fn(text)
        _push(user_id, _finalize_text(res))
    except Exception as e:
        logger.error(f"finance worker error: {e}")
        _push(user_id, "資金計画でエラーが発生しました。")

def _worker_ai(user_id: str, text: str):
    try:
        fn = _resolve_rag_if_needed()
        if not fn:
            _push(user_id, "AI機能が利用できません。")
            return
        ans = fn(text) or {}
        out = ans.get("answer", "回答を取得できませんでした。")
        _push(user_id, _finalize_text(out))
    except Exception as e:
        logger.error(f"ai worker error: {e}")
        _push(user_id, "AIでエラーが発生しました。")

# ======================================================================
# Postback resolver
# ======================================================================
def _resolve_postback_key(data: str) -> Optional[str]:
    if data in RICHMENU_FIXED_RESPONSES:
        return data
    if data in RICHMENU_KEYWORD_MAPPING:
        return RICHMENU_KEYWORD_MAPPING[data]
    for prefix in ["action=", "data="]:
        if data.startswith(prefix):
            val = data[len(prefix):]
            if val in RICHMENU_FIXED_RESPONSES:
                return val
            if val in RICHMENU_KEYWORD_MAPPING:
                return RICHMENU_KEYWORD_MAPPING[val]
    return None

# ======================================================================
# Webhook endpoint (IMPORTANT: /webhook) — use app.include_router(router, prefix="/line")
# ======================================================================
@router.post("/webhook")
async def webhook(request: Request, background: BackgroundTasks):
    if not handler or not LINE_SDK_AVAILABLE:
        logger.error("handler not available")
        return JSONResponse({"error": "handler_unavailable"}, status_code=500)

    try:
        body = await request.body()
        sig = request.headers.get("X-Line-Signature") or ""
        handler.handle(body.decode("utf-8"), sig)
        return Response(status_code=200)
    except Exception as e:
        logger.error(f"webhook error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

# ======================================================================
# Handlers
# ======================================================================
if handler and LINE_SDK_AVAILABLE:
    @handler.add(FollowEvent)
    def on_follow(event):
        try:
            user_id = event.source.user_id
            _reply_or_push(event.reply_token, user_id, RICHMENU_FIXED_RESPONSES["follow_greeting"])
        except Exception as e:
            logger.error(f"follow handler error: {e}")

    @handler.add(MessageEvent, message=TextMessageContent)
    def on_message(event):
        try:
            user_id = event.source.user_id
            text_raw = event.message.text or ""
            text = _normalize_button_text(text_raw)
            reply_token = event.reply_token
            if not text: return
            if dup_guard.seen(user_id, f"msg:{text[:64]}"): return

            # Resolve richmenu
            key = None
            if text in RICHMENU_FIXED_RESPONSES:
                key = text
            else:
                # exact-match after normalization
                mapped = RICHMENU_KEYWORD_MAPPING.get(text)
                if mapped:
                    key = mapped

            if key:
                if key == K_AI:
                    if not _has_consent_sync(user_id):
                        liff_url = _make_consent_link(user_id)
                        if FLEX_AVAILABLE:
                            try:
                                flex_msg = build_consent_flex(liff_url)
                                if not _reply_or_push_flex(reply_token, user_id, flex_msg):
                                    _reply_or_push(reply_token, user_id, _not_consent_msg_for(user_id))
                            except Exception as flex_err:
                                logger.error(f"Flex build/send error: {flex_err}")
                                _reply_or_push(reply_token, user_id, _not_consent_msg_for(user_id))
                        else:
                            _reply_or_push(reply_token, user_id, _not_consent_msg_for(user_id))
                        return
                    sessions.set_mode(user_id, "ai")
                    _reply_or_push(reply_token, user_id, RICHMENU_FIXED_RESPONSES[key])
                    return

                if key == K_SHARE:
                    share_url = _resolve_share_url()
                    if share_url:
                        _reply_or_push(reply_token, user_id, f"友だちに共有するにはこちらを開いてください：\\n{share_url}")
                    else:
                        _reply_or_push(reply_token, user_id, "共有ページの設定が見つかりませんでした。管理者にお問い合わせください。")
                    return

                if key == "資金計画":
                    sessions.set_mode(user_id, "finance")
                    _reply_or_push(reply_token, user_id, "📊 試算中です。少しお待ちください…")
                    threading.Thread(target=_worker_finance, args=(user_id, text), daemon=True).start()
                    return

                # other fixed responses
                _reply_or_push(reply_token, user_id, RICHMENU_FIXED_RESPONSES.get(key, "（設定が見つかりません）"))
                return

            # Mode routing
            mode = sessions.get_mode(user_id)
            if mode == "finance":
                _reply_or_push(reply_token, user_id, "📊 試算中です。少しお待ちください…")
                threading.Thread(target=_worker_finance, args=(user_id, text), daemon=True).start()
                return
            if mode == "ai":
                _reply_or_push(reply_token, user_id, "🔎 少しお待ちください…")
                threading.Thread(target=_worker_ai, args=(user_id, text_raw), daemon=True).start()
                return

            # Fallback guidance (order only, sentences unchanged)
            fallback = (
                "ご質問ありがとうございます😊\\n\\n"
                "目的のボタンをタップしてください👇\\n"
                f"{FALLBACK_ORDER}\\n\\n"
                "具体的なご質問もお気軽にどうぞ✨"
            )
            _reply_or_push(reply_token, user_id, fallback)
        except Exception as e:
            logger.error(f"message handler error: {e}")
            try:
                _reply_or_push(event.reply_token, event.source.user_id, "一時的にエラーが発生しました。時間をおいてお試しください。")
            except Exception:
                pass

    @handler.add(PostbackEvent)
    def on_postback(event):
        try:
            user_id = event.source.user_id
            data = (event.postback.data or "").strip()
            reply_token = event.reply_token
            if dup_guard.seen(user_id, f"post:{data[:64]}"): return

            key = _resolve_postback_key(data)

            if key:
                if key == K_AI:
                    if not _has_consent_sync(user_id):
                        liff_url = _make_consent_link(user_id)
                        if FLEX_AVAILABLE:
                            try:
                                flex_msg = build_consent_flex(liff_url)
                                if not _reply_or_push_flex(reply_token, user_id, flex_msg):
                                    _reply_or_push(reply_token, user_id, _not_consent_msg_for(user_id))
                            except Exception as flex_err:
                                logger.error(f"Postback flex error: {flex_err}")
                                _reply_or_push(reply_token, user_id, _not_consent_msg_for(user_id))
                        else:
                            _reply_or_push(reply_token, user_id, _not_consent_msg_for(user_id))
                        return
                    sessions.set_mode(user_id, "ai")
                    _reply_or_push(reply_token, user_id, RICHMENU_FIXED_RESPONSES[key])
                    return

                if key == K_SHARE:
                    share_url = _resolve_share_url()
                    if share_url:
                        _reply_or_push(reply_token, user_id, f"友だちに共有するにはこちらを開いてください：\\n{share_url}")
                    else:
                        _reply_or_push(reply_token, user_id, "共有ページの設定が見つかりませんでした。管理者にお問い合わせください。")
                    return

                if key == "資金計画":
                    sessions.set_mode(user_id, "finance")
                    _reply_or_push(reply_token, user_id, "📊 試算中です。少しお待ちください…")
                    threading.Thread(target=_worker_finance, args=(user_id, data), daemon=True).start()
                    return

                _reply_or_push(reply_token, user_id, RICHMENU_FIXED_RESPONSES.get(key, "（設定が見つかりません）"))
                return

            _reply_or_push(
                reply_token, user_id,
                f"目的のボタンをタップしてください👇\\n{FALLBACK_ORDER}"
            )
        except Exception as e:
            logger.error(f"postback handler error: {e}")

# ======================================================================
# After-consent push (unchanged)
# ======================================================================
@router.post("/line/after-consent")
async def after_consent(request: Request):
    request_id = getattr(request.state, "request_id", str(uuid4())[:8])
    try:
        logger.info(f"[{request_id}] after-consent: Processing request")
        try:
            payload = await request.json()
        except Exception as e:
            logger.error(f"[{request_id}] invalid json: {e}")
            return JSONResponse({"ok": False, "error": "invalid_json", "detail": str(e)}, status_code=400)

        uid_hdr = request.headers.get("X-User-Id") or ""
        uid_body = (payload or {}).get("user_id") or ""
        user_token = (payload or {}).get("user_token") or request.headers.get("X-User-Token") or request.headers.get("user_token") or ""

        if _is_line_uid(uid_hdr):
            user_id = uid_hdr
        elif _is_line_uid(uid_body):
            user_id = uid_body
        else:
            user_id = _extract_user_id_from_token(user_token or "")

        if not _is_line_uid(user_id):
            logger.error(f"[{request_id}] cannot resolve LINE userId")
            return JSONResponse({"ok": False, "reason": "no_line_userid"}, status_code=400)

        logger.info(f"[{request_id}] final user_id: {user_id[:8]}...")

        sessions.set_mode(user_id, "ai")
        ok = _push(user_id, RICHMENU_FIXED_RESPONSES[K_AI])
        if ok:
            _push(user_id, "🤖 AI相談を開始しました！何でもお聞きください😊")
            return JSONResponse({
                "ok": True,
                "success": True,
                "user_id_hash": hashlib.md5(user_id.encode()).hexdigest()[:8],
                "session_mode": "ai",
                "request_id": request_id,
                "timestamp": datetime.now().isoformat()
            }, status_code=200)
        else:
            logger.error(f"[{request_id}] push failed")
            return JSONResponse({"ok": False, "error": "push_failed", "request_id": request_id}, status_code=500)

    except Exception as e:
        logger.error(f"[{request_id}] after-consent unexpected: {e}")
        logger.error(traceback.format_exc())
        return JSONResponse({"ok": False, "error": "internal_error", "detail": str(e),
                             "request_id": request_id, "timestamp": datetime.now().isoformat()}, status_code=500)

# ======================================================================
# Consent record endpoint (no-op)
# ======================================================================
class ConsentPayload(BaseModel):
    user_token: str
    consent: bool = True
    utm: dict | None = None

@router.post("/line/consent", tags=["liff"], status_code=204)
async def record_consent(req: Request, payload: ConsentPayload) -> Response:
    try:
        logger.info(f"[consent] token={payload.user_token} consent={payload.consent} utm={payload.utm}")
        return Response(status_code=204)
    except Exception as e:
        logger.error(f"record_consent error: {e}")
        return Response(status_code=204)

# ======================================================================
# Health
# ======================================================================
@router.get("/line/health")
def health():
    return {
        "status": "ok" if (LINE_SDK_AVAILABLE and handler and _ensure_api()) else "degraded",
        "ts": datetime.now().isoformat(),
        "timeout": LINE_RESPONSE_TIMEOUT,
    }