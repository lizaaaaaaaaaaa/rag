# api/routers/line_bot_ultra_fast.py
# 同意フロー強化版：/line/after-consent で UID（U...）を最優先使用
# - リッチメニュー文言は既存のまま
# - 応答速度を落とさない（非同期/スレッド・ACK 200）
# - LIFF からの X-User-Id / body.user_id を最優先で to に使う

import logging, os, re, time, hashlib, threading, sys, pathlib, importlib, json, traceback
from datetime import datetime
from typing import Dict, Optional, Any, Tuple
from urllib.parse import urlencode, urlparse, parse_qsl, urlunparse
from uuid import uuid4

from fastapi import APIRouter, Request, BackgroundTasks, Body, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# -------------------------------
# UTM 付与（line_utils が無い環境でも動くフォールバック）
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
# RAG / 資金計画：遅延ロード
# ======================================================================
ROOT = pathlib.Path(__file__).resolve().parents[2]  # .../RAG-LLM-Project
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_get_rag_response = None
def _resolve_rag_if_needed():
    """初回だけRAGを解決（以降はキャッシュ）"""
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
    """初回だけ資金計画を解決（以降はキャッシュ）"""
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
# 出典/参考/資料などの脚注文言を**本文から**一切表示しない（sources JSONは別）
# ======================================================================
def _strip_citations(text: str) -> str:
    if not text:
        return text

    # 行頭見出し（参考/資料/出典）
    text = re.sub(r"(?m)^\s*(参考|参考資料|参考文献|資料|出典|引用)\s*[:：].*$", "", text)

    # 本文中の「参考: … / 資料: … / 出典: …」も行末まで削除
    text = re.sub(r"(参考|参考資料|資料|出典|引用)\s*[:：].*$", "", text, flags=re.MULTILINE)

    # 「【出典】…」ブロック以降を削る
    text = re.sub(r"【\s*(出典|参考|資料)\s*】[\s\S]*?$", "", text, flags=re.MULTILINE)

    # (p.12) / (p. 12) / (p:12) / (p：12) / (p.?) / （p.？） 等（半角/全角）
    text = re.sub(r"[（(]\s*[pP]\s*[\.\:：]?\s*(\d+|[?？]+)\s*[)）]", "", text)

    # 連続改行の整形
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text

# ======================================================================
# ★ 追加：プレースホルダー（○○/TBD/？？？ 等）の最終ガード
# ======================================================================
_PLACEHOLDER_RE = re.compile(r"(○○|〇〇|××|X{2,}|XXXX|TBD|未定|要確認|？？？|\?{2,}|＜.*?＞|ここに.*?を書く)")

def _strip_placeholders(t: str) -> str:
    if not t:
        return t
    tt = _PLACEHOLDER_RE.sub("（資料に記載なし）", t)
    # 置換だらけで短すぎる場合は安全文に差し替え
    if "（資料に記載なし）" in tt and len(tt) < 40:
        return "資料内に該当情報が見つかりませんでした。必要であれば担当へ確認します。"
    return tt

def _finalize_text(t: str) -> str:
    """送信直前の最終整形：脚注断片を除去 → プレースホルダーを除去"""
    return _strip_placeholders(_strip_citations(t or "")).strip()

# ======================================================================
# LINE SDK v3（Flex を含めた完全インポート）
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
    class WebhookHandler:  # ダミー
        def __init__(self, *a, **k): ...
        def add(self, *a, **k):
            def deco(f): return f
            return deco
        def handle(self, *a, **k): ...

# ======================================================================
# ルーター
# ======================================================================
router = APIRouter(prefix="", tags=["line-ultra-fast"])

# ======================================================================
# 設定
# ======================================================================
LINE_RESPONSE_TIMEOUT = int(os.getenv("LINE_RESPONSE_TIMEOUT", "12"))  # 既定12秒
SESSION_TTL = int(os.getenv("SESSION_TTL_MINUTES", "30")) * 60

# ▼ PUBLIC_BASE_URL はあれば使う。無ければ PUBLIC_API_BASE をフォールバックに（安全側）
PUBLIC_BASE_URL = (os.getenv("PUBLIC_BASE_URL") or os.getenv("PUBLIC_API_BASE") or "").rstrip("/")
if not PUBLIC_BASE_URL:
    logger.warning("PUBLIC_BASE_URL is not set. Consent link generation may be relative.")

# LIFF の同意用 URL（最優先で使用）
LIFF_CONSENT_URL = os.getenv("LIFF_CONSENT_URL", "").rstrip("/")

# ======================================================================
# 固定テンプレ（※リッチメニューの文言は変更しない）
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

RICHMENU_KEYWORD_MAPPING: Dict[str, str] = {
    "🤖 AI相談": "🤖 AI相談",
    "AI住まいサイト": "AI住まいサイト", "🌐 AI住まいサイト": "AI住まいサイト", "サイト": "AI住まいサイト", "ホームページ": "AI住まいサイト",
    "資料請求": "資料請求", "📋 資料請求": "資料請求",
    "展示場来場予約": "展示場来場予約", "📍 展示場来場　予約": "展示場来場予約", "来場予約": "展示場来場予約",
    "資金計画": "資金計画", "💴 資金計画": "資金計画", "💰 資金計画": "資金計画",
    "チャット相談": "チャット相談", "💬チャット相談": "チャット相談", "チャット": "チャット相談",
    # 可能性のある英語/シンプルdata対策
    "ai_consultation": "🤖 AI相談",
    "ai_site": "AI住まいサイト",
    "document_request": "資料請求",
    "visit_reservation": "展示場来場予約",
    "financial_plan": "資金計画",
    "chat_consultation": "チャット相談",
}

# ======================================================================
# セッション/重複ガード
# ======================================================================
class SessionManager:
    def __init__(self):
        self._modes: Dict[str, Tuple[str, float]] = {}  # user_id -> (mode, timestamp)

    def get_mode(self, user_id: str) -> Optional[str]:
        record = self._modes.get(user_id)
        if not record: return None
        mode, ts = record
        if (time.time() - ts) > SESSION_TTL:
            del self._modes[user_id]
            return None
        return mode

    def set_mode(self, user_id: str, mode: str):
        self._modes[user_id] = (mode, time.time())

sessions = SessionManager()

class DuplicateGuard:
    def __init__(self, ttl: int = 300):
        self._seen: Dict[str, float] = {}
        self._ttl = ttl

    def seen(self, user_id: str, key: str) -> bool:
        now = time.time()
        full_key = f"{user_id}:{key}"
        # 期限切れを削除
        expired = [k for k, ts in self._seen.items() if (now - ts) > self._ttl]
        for k in expired: del self._seen[k]
        # 重複チェック
        if full_key in self._seen: return True
        self._seen[full_key] = now
        return False

dup_guard = DuplicateGuard(ttl=15)

# ======================================================================
# SDK初期化
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
# 同意関連（URL生成・文面）
# ======================================================================
def _make_user_token(user_id: str) -> str:
    """一時トークン生成"""
    secret = os.getenv("SESSION_SECRET", "kinoe-ai-session")
    data = f"{user_id}:{time.time()}"
    h = hashlib.sha256((data + secret).encode()).hexdigest()
    return f"{user_id}.{h[:16]}"

def _make_consent_link(user_id: str) -> str:
    """
    LIFF同意画面URL生成：X-User-Idヘッダーで戻る想定
    1) LIFF_CONSENT_URL があればそちら優先（トークン付与）
    2) なければ PUBLIC_BASE_URL/line-consent 形式（フォールバック）
    """
    token = _make_user_token(user_id)
    if LIFF_CONSENT_URL:
        sep = "&" if "?" in LIFF_CONSENT_URL else "?"
        return f"{LIFF_CONSENT_URL}{sep}user_token={token}"
    else:
        return f"{PUBLIC_BASE_URL}/line-consent?user_token={token}"

def _not_consent_msg_for(user_id: str) -> str:
    """未同意の場合の文面（リンク付き）"""
    link = _make_consent_link(user_id)
    return (
        "🔔 AI相談を利用するには、最初に同意が必要です。\n\n"
        f"こちらから同意をお願いします：\n{link}"
    )

def _is_line_uid(s: str) -> bool:
    """文字列がLINE UID (U...) 形式か？"""
    return bool(s and s.startswith("U") and len(s) > 20)

def _extract_user_id_from_token(token: str) -> str:
    """トークンから user_id を抽出（例: 'Uxxxx.hash' → 'Uxxxx'）"""
    if not token: return ""
    parts = token.split(".")
    if parts and _is_line_uid(parts[0]): return parts[0]
    return ""

def _has_consent_sync(user_id: str) -> bool:
    """
    実装例：実際の同意状況を DB やキャッシュからチェック
    ここでは仮に「常に True」として簡略化
    """
    return True  # 実装時は DB などで確認

# ======================================================================
# Reply/Push
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
    """
    Flex メッセージを送信
    ※ flex_msg は既に FlexMessage インスタンス
    """
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
# Flex メッセージ構築（同意ボタン用）
# ======================================================================
def build_consent_flex(liff_url: str) -> FlexMessage:
    """
    同意が必要な場合の Flex メッセージ
    - タイトル: 「🤖 AI相談」
    - 説明 + 同意ボタン
    """
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
                    text="・AIに個人情報は入力しないでください\n・AIの回答は必ずしも正しいとは限りません\n・最終案内はスタッフが行います",
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
# ワーカー（資金計画・AI）
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
# Postback データ解決
# ======================================================================
def _resolve_postback_key(data: str) -> Optional[str]:
    """
    Postbackデータから RICHMENU_FIXED_RESPONSES のキーを解決
    action=XXX / data=XXX 形式に対応
    """
    if data in RICHMENU_FIXED_RESPONSES:
        return data
    if data in RICHMENU_KEYWORD_MAPPING:
        return RICHMENU_KEYWORD_MAPPING[data]
    # action= / data= の形式を試す
    for prefix in ["action=", "data="]:
        if data.startswith(prefix):
            val = data[len(prefix):]
            if val in RICHMENU_FIXED_RESPONSES:
                return val
            if val in RICHMENU_KEYWORD_MAPPING:
                return RICHMENU_KEYWORD_MAPPING[val]
    return None

# ======================================================================
# Webhook エンドポイント
# ======================================================================
@router.post("/line/callback")
async def callback(request: Request, background: BackgroundTasks):
    if not handler or not LINE_SDK_AVAILABLE:
        logger.error("handler not available")
        return JSONResponse({"error": "handler_unavailable"}, status_code=500)

    try:
        body = await request.body()
        sig = request.headers.get("X-Line-Signature") or ""
        handler.handle(body.decode("utf-8"), sig)
        return Response(status_code=200)
    except Exception as e:
        logger.error(f"callback error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

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
            text = (event.message.text or "").strip()
            reply_token = event.reply_token
            if not text: return
            if dup_guard.seen(user_id, f"msg:{text[:64]}"): return

            # リッチメニュー固定応答
            key = None
            if text in RICHMENU_FIXED_RESPONSES:
                key = text
            else:
                for k, mapped in RICHMENU_KEYWORD_MAPPING.items():
                    if k == text:
                        key = mapped
                        break

            # リッチメニュー項目にヒット
            if key:
                if key == "🤖 AI相談":
                    # 未同意なら Flex ボタン（エラー時はテキストにフォールバック）
                    if not _has_consent_sync(user_id):
                        liff_url = _make_consent_link(user_id)
                        if FLEX_AVAILABLE:
                            try:
                                flex_msg = build_consent_flex(liff_url)
                                success = _reply_or_push_flex(reply_token, user_id, flex_msg)
                                if success:
                                    logger.info(f"Sent Flex consent to {user_id[:8]}...")
                                else:
                                    logger.warning(f"Flex send failed for {user_id[:8]}..., falling back to text")
                                    _reply_or_push(reply_token, user_id, _not_consent_msg_for(user_id))
                            except Exception as flex_err:
                                logger.error(f"Flex build/send error: {flex_err}, falling back to text")
                                _reply_or_push(reply_token, user_id, _not_consent_msg_for(user_id))
                        else:
                            _reply_or_push(reply_token, user_id, _not_consent_msg_for(user_id))
                        return
                    sessions.set_mode(user_id, "ai")
                elif key == "資金計画":
                    sessions.set_mode(user_id, "finance")
                _reply_or_push(reply_token, user_id, RICHMENU_FIXED_RESPONSES[key])
                return

            # モードに応じて振り分け
            mode = sessions.get_mode(user_id)
            if mode == "finance":
                _reply_or_push(reply_token, user_id, "📊 試算中です。少しお待ちください…")
                threading.Thread(target=_worker_finance, args=(user_id, text), daemon=True).start()
                return
            if mode == "ai":
                _reply_or_push(reply_token, user_id, "🔎 少しお待ちください…")
                threading.Thread(target=_worker_ai, args=(user_id, text), daemon=True).start()
                return

            # どれにも該当しない通常テキストへのフォールバック
            fallback = (
                "ご質問ありがとうございます😊\n\n"
                "目的のボタンをタップしてください👇\n"
                "🤖 AI相談 / 🌐 AI住まいサイト / 📋 資料請求 / 📍 来場予約 / 💬 チャット相談\n\n"
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
                if key == "🤖 AI相談":
                    if not _has_consent_sync(user_id):
                        liff_url = _make_consent_link(user_id)
                        if FLEX_AVAILABLE:
                            try:
                                flex_msg = build_consent_flex(liff_url)
                                success = _reply_or_push_flex(reply_token, user_id, flex_msg)
                                if not success:
                                    _reply_or_push(reply_token, user_id, _not_consent_msg_for(user_id))
                            except Exception as flex_err:
                                logger.error(f"Postback flex error: {flex_err}")
                                _reply_or_push(reply_token, user_id, _not_consent_msg_for(user_id))
                        else:
                            _reply_or_push(reply_token, user_id, _not_consent_msg_for(user_id))
                        return
                    sessions.set_mode(user_id, "ai")
                elif key == "資金計画":
                    sessions.set_mode(user_id, "finance")
                _reply_or_push(reply_token, user_id, RICHMENU_FIXED_RESPONSES[key])
                return

            _reply_or_push(
                reply_token, user_id,
                "目的のボタンをタップしてください👇\n🤖 AI相談 / 🌐 AI住まいサイト / 📋 資料請求 / 📍 来場予約 / 💬 チャット相談"
            )
        except Exception as e:
            logger.error(f"postback handler error: {e}")

# ======================================================================
# 同意完了後のプッシュ（AI相談を自動開始）— UID最優先
# ======================================================================
@router.post("/line/after-consent")
async def after_consent(request: Request):
    """
    同意完了後のLINE通知（強化版）
    - X-User-Id / body.user_id が U… なら **最優先で to に使用**
    - それ以外は user_token から解決（従来互換）
    """
    request_id = getattr(request.state, "request_id", str(uuid4())[:8])
    try:
        logger.info(f"[{request_id}] after-consent: Processing request")

        # JSON 取得
        try:
            payload = await request.json()
        except Exception as e:
            logger.error(f"[{request_id}] invalid json: {e}")
            return JSONResponse({"ok": False, "error": "invalid_json", "detail": str(e)}, status_code=400)

        # 1) UID を最優先で解決
        uid_hdr = request.headers.get("X-User-Id") or ""
        uid_body = (payload or {}).get("user_id") or ""
        user_token = (payload or {}).get("user_token") or request.headers.get("X-User-Token") or request.headers.get("user_token") or ""

        if _is_line_uid(uid_hdr):
            user_id = uid_hdr
        elif _is_line_uid(uid_body):
            user_id = uid_body
        else:
            # 2) フォールバック：トークンから抽出
            user_id = _extract_user_id_from_token(user_token or "")

        if not _is_line_uid(user_id):
            logger.error(f"[{request_id}] cannot resolve LINE userId")
            return JSONResponse({"ok": False, "reason": "no_line_userid"}, status_code=400)

        logger.info(f"[{request_id}] final user_id: {user_id[:8]}...")

        # セッションをAIにセットし、既定の文面を送信（文言変更なし）
        sessions.set_mode(user_id, "ai")
        ok = _push(user_id, RICHMENU_FIXED_RESPONSES["🤖 AI相談"])
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
# 追加: LIFFの「同意して開始」ボタンが叩く記録API（まずは204だけ返す）
# ======================================================================
class ConsentPayload(BaseModel):
    user_token: str
    consent: bool = True
    utm: dict | None = None  # 任意でそのまま受ける

@router.post("/line/consent", tags=["liff"], status_code=204)
async def record_consent(req: Request, payload: ConsentPayload) -> Response:
    try:
        logger.info(f"[consent] token={payload.user_token} consent={payload.consent} utm={payload.utm}")
        return Response(status_code=204)
    except Exception as e:
        logger.error(f"record_consent error: {e}")
        return Response(status_code=204)

# ======================================================================
# 簡易ステータス
# ======================================================================
@router.get("/line/health")
def health():
    return {
        "status": "ok" if (LINE_SDK_AVAILABLE and handler and _ensure_api()) else "degraded",
        "ts": datetime.now().isoformat(),
        "timeout": LINE_RESPONSE_TIMEOUT,
    }