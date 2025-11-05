# api/routers/line_bot_ultra_fast.py
# 同意フロー強化版 + 友だち紹介（LIFF）対応 + 絵文字ゆらぎ吸収
# - リッチメニュー文言は既存のまま（テキストは変更しない）
# - 応答速度は維持（ハンドラ内は最小限、非同期ACK）
# - /webhook と /line/webhook をどちらも受け付け、常に 200 を返す
# - 友だち紹介は Postback(action=share) でも テキスト送信 でも反応

from __future__ import annotations

import logging, os, re, time, hashlib, threading, sys, pathlib, importlib, json, traceback
from datetime import datetime
from typing import Dict, Optional, Any, Tuple
from urllib.parse import urlencode, urlparse, parse_qsl, urlunparse
from urllib.parse import quote  # ← 共有用のクエリ付与で使用
from uuid import uuid4

from fastapi import APIRouter, Request, BackgroundTasks
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ======================================================================
# UTM 付与（line_utils が無い環境でも動くフォールバック）
# ======================================================================

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
except Exception:  # pragma: no cover
    with_utm = _with_utm_fallback  # type: ignore

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
    for cand in (
        "api.services.rag_chain",
        "services.rag_chain",
        "rag.rag_chain",
        "rag_chain",
    ):
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
    for cand in (
        "api.routers.line_bot_financial_planner",
        "line_bot_financial_planner",
        "api.routers.financial_api",
        "financial_api",
        "services.financial_api",
    ):
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

_DEF_FOOTER_RE_HEAD = re.compile(r"(?m)^\s*(参考|参考資料|参考文献|資料|出典|引用)\s*[:：].*$")
_DEF_FOOTER_RE_INLINE = re.compile(r"(参考|参考資料|資料|出典|引用)\s*[:：].*$", flags=re.MULTILINE)
_DEF_FOOTER_RE_BLOCK = re.compile(r"【\s*(出典|参考|資料)\s*】[\s\S]*?$", flags=re.MULTILINE)
_DEF_PAGE_RE = re.compile(r"[（(]\s*[pP]\s*[\.:：]?\s*(\d+|[?？]+)\s*[)）]")

_PLACEHOLDER_RE = re.compile(r"(○○|〇〇|××|X{2,}|XXXX|TBD|未定|要確認|？？？|\?{2,}|＜.*?＞|ここに.*?を書く)")

def _strip_citations(text: str) -> str:
    if not text:
        return text
    text = _DEF_FOOTER_RE_HEAD.sub("", text)
    text = _DEF_FOOTER_RE_INLINE.sub("", text)
    text = _DEF_FOOTER_RE_BLOCK.sub("", text)
    text = _DEF_PAGE_RE.sub("", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()

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
# LINE SDK v3（Flex を含めた完全インポート）
# ======================================================================

try:
    from linebot.v3 import WebhookHandler
    from linebot.v3.messaging import (
        Configuration,
        ApiClient,
        MessagingApi,
        ReplyMessageRequest,
        PushMessageRequest,
        TextMessage,
        ApiException,
        FlexMessage,
        FlexBubble,
        FlexBox,
        FlexText,
        FlexButton,
        FlexSeparator,
        URIAction,
    )
    from linebot.v3.webhooks import (
        MessageEvent,
        TextMessageContent,
        PostbackEvent,
        FollowEvent,
    )
    LINE_SDK_AVAILABLE = True
    FLEX_AVAILABLE = True
    logger.info("✅ LINE Bot SDK v3 with Flex imported")
except Exception as e:  # pragma: no cover
    LINE_SDK_AVAILABLE = False
    FLEX_AVAILABLE = False
    logger.error(f"❌ LINE Bot SDK import failed: {e}")

    class WebhookHandler:  # ダミー
        def __init__(self, *a, **k): ...
        def add(self, *a, **k):
            def deco(f):
                return f
            return deco
        def handle(self, *a, **k): ...

# ======================================================================
# ルーター
# ======================================================================

router = APIRouter(prefix="", tags=["line-ultra-fast"])

# ======================================================================
# 設定 / 環境変数
# ======================================================================

LINE_RESPONSE_TIMEOUT = int(os.getenv("LINE_RESPONSE_TIMEOUT", "12"))  # 既定12秒
SESSION_TTL = int(os.getenv("SESSION_TTL_MINUTES", "30")) * 60

# ▼ PUBLIC_BASE_URL はあれば使う。無ければ PUBLIC_API_BASE をフォールバックに（安全側）
PUBLIC_BASE_URL = (
    os.getenv("PUBLIC_BASE_URL") or os.getenv("PUBLIC_API_BASE") or ""
).rstrip("/")
if not PUBLIC_BASE_URL:
    logger.warning("PUBLIC_BASE_URL is not set. Consent link generation may be relative.")

# LIFF（同意ページ）
LIFF_CONSENT_URL = os.getenv("LIFF_CONSENT_URL", "").rstrip("/")

# 友だち紹介 LIFF
LIFF_ID_SHARE = os.getenv("LIFF_ID_SHARE", "").strip()
LIFF_SHARE_URL = os.getenv("LIFF_SHARE_URL", "").strip()
PUBLIC_FRONT_BASE = os.getenv("PUBLIC_FRONT_BASE", "").rstrip("/")  # 例: https://rag-frontend-...run.app

# ======================================================================
# 固定テンプレ（※リッチメニューの文言は変更しない）
# ======================================================================

RICHMENU_FIXED_RESPONSES: Dict[str, str] = {
    "follow_greeting": """こんにちは！キノエデザイン住まいAIプランナーです。
この度は友だち追加ありがとうございます✨

このAIは住宅検討の参考用に設計された自動応答です。
最終的な、ご提案はスタッフが行います。

また、AIに個人情報は入力しないでください。
本チャットでは個人情報や機微情報の入力は不要です。
誤って入力された情報は目的外に利用せず、最短で削除/匿名化します。
個人情報を伴うご相談は、専用フォーム（同意取得・暗号化送信）をご利用ください。

📸💪 キノエデザインの設計思想とAI技術が、理想の住まいづくりを完全サポート！
📱💬まずはリッチメニューから気になる項目をタップ
または、直接メッセージでご質問ください。
📍 各展示場でも実際にご相談いただけます""",

"住まいAI相談": """🤖 住まいAI相談を開始します！
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

"住まいAIサイト": """🌐 住まいAIサイトのご案内
キノエデザインの住まいAI情報サイトをご紹介します。（家づくりの疑問にAIがお答えします）

🏠
気になることや、お悩みをAIが、お答え・解決するホームページです。

ZINE、ダウンロードもできます。

※ AIに個人情報は入力しないでください／保存OFF（既定）
※ このAIは住宅検討の参考用に設計された自動応答です。
※ AIの回答は必ずしも正しいとは限りません。→ 確定案内はスタッフが行います。
※ ご質問の内容により、AIの回答までお時間を頂戴する場合がございます。
※ ご使用の前に、必ず同意が必要となります。何卒ご理解賜りますようお願い申し上げます。

📱 キノエデザイン住まいAIプランナー
ホームページURL：
https://ai.kinoedesign.co.jp/line/""",

"チャット相談": """💬 スタッフとのご相談
AIより、人の方がお好みの方はこちら。
スタッフとチャット相談。
お気軽にメッセージどうぞ！

【対応時間】
営業時間：9:00-18:00

📱 ご相談方法：
・このLINEでの直接チャット相談
・お電話での相談：0794-82-8540
・展示場での対面相談：https://kinoedesign.co.jp/consultation/
・メールでのお問い合わせ：https://kinoedesign.co.jp/contact/

お気軽にお声かけください！""",

"展示場来場予約": """📍 展示場のご来場予約:
24 時間いつでも、予約OKです。
ご予約の際は、下記の来場予約ホームページURLよりご送信ください。
来場予約ホームページURL：
【https://kinoedesign.co.jp/consultation/ 】""",

"資料請求": """📋資料請求ありがとうございます！
下記のリンクより、資料をご請求ください。
リンク：https://kinoedesign.co.jp/request/""",
}

# 表記ゆらぎ吸収用マップ（文言は変更しない）
# ★ 修正：AI相談系のゆらぎを「AI相談」に正規化
RICHMENU_KEYWORD_MAPPING: Dict[str, str] = {
    # 住まいAI相談 → AI相談 に正規化（ここが今回の重要ポイント）
    "住まいAI相談": "AI相談",
    "🤖 住まいAI相談": "AI相談",
    "🤖 AI相談": "AI相談",

    "住まいAIサイト": "住まいAIサイト",
    "🌐 住まいAIサイト": "住まいAIサイト",
    "サイト": "住まいAIサイト",
    "ホームページ": "住まいAIサイト",

    "チャット相談": "チャット相談",
    "💬チャット相談": "チャット相談",
    "チャット": "チャット相談",

    "展示場来場予約": "展示場来場予約",
    "📍 展示場来場　予約": "展示場来場予約",
    "来場予約": "展示場来場予約",

    "資料請求": "資料請求",
    "📋 資料請求": "資料請求",
}

# ======================================================================
# 友だち紹介：URL 生成 + ゆらぎキー
# ======================================================================

_ZEN = str.maketrans({"　": " "})
_RM = re.compile(r"[\s\uFE0F\u200D]+")

def _key(s: str) -> str:
    s = (s or "").translate(_ZEN)
    s = _RM.sub("", s)
    return s.replace("友達", "友だち")

SHARE_KEYS = {
    _key("🧑‍🤝‍🧑 友達に紹介"),
    _key("🧑‍🤝‍🧑友達に紹介"),
    _key("友達に紹介"),
    _key("友だちに紹介"),
}

def _share_url() -> str:
    """友だち紹介で開く LIFF or 静的HTML の URL を決定（空文字は返さない）"""
    if LIFF_SHARE_URL:
        logger.info(f"[share] using LIFF_SHARE_URL={LIFF_SHARE_URL}")
        return LIFF_SHARE_URL
    if LIFF_ID_SHARE:
        url = f"https://liff.line.me/{LIFF_ID_SHARE}"
        logger.info(f"[share] fallback LIFF_ID_SHARE -> {url}")
        return url
    if PUBLIC_FRONT_BASE:
        url = f"{PUBLIC_FRONT_BASE}/web/liff/share.html"
        logger.info(f"[share] fallback PUBLIC_FRONT_BASE -> {url}")
        return url
    logger.warning("[share] no LIFF url found; using safe placeholder")
    return "https://example.com/web/liff/share.html"

from typing import List

# =========================
# 友だち紹介：Flex（URL生表示はしない）
# =========================

def _get_liff_share_url() -> str:
    """既存の環境変数を利用してLIFFのベースURLを取得"""
    return os.getenv("LIFF_SHARE_URL", "").strip()

def _get_official_line_share_url() -> str:
    """互換：共有する“公式LINE/サイト”URL（旧：url パラメータとして渡す用）"""
    return os.getenv("LINE_OA_SHARE_URL", "https://ai.kinoedesign.co.jp/").strip()

def _get_official_invite_url() -> str:
    """
    公式アカウントの“友だち追加（招待）URL”を取得
    優先順：OFFICIAL_LINE_INVITE_URL → LINE_OA_SHARE_URL → 既定（管理画面で取得したURL）
    """
    return (
        os.getenv("OFFICIAL_LINE_INVITE_URL", "").strip()
        or os.getenv("LINE_OA_SHARE_URL", "").strip()
        or "https://lin.ee/tXUD9eu"
    )

def build_share_flex() -> "FlexMessage":
    """友だち紹介のFlexカード（生URLは出さない/ボタンのみ）"""
    liff_base = _get_liff_share_url()
    invite    = _get_official_invite_url()
    oa_url    = _get_official_line_share_url()  # 互換：site/url フォールバック

    # 共有内容
    title = "AI相談のご紹介"
    desc  = "キノエデザイン住まいAIプランナーの公式LINEです。"

    # LIFFに共有内容を引き渡す（invite / title / desc [+ 互換の url]）
    if liff_base:
        liff_url = (
            f"{liff_base}"
            f"?invite={quote(invite)}"
            f"&title={quote(title)}"
            f"&desc={quote(desc)}"
            f"&url={quote(oa_url)}"  # 互換維持：旧 share.html が参照する場合に備える
        )
    else:
        # 念のためのフォールバック（LIFF未設定時は公式LINE/サイトURLへ）
        liff_url = invite or oa_url

    if not FLEX_AVAILABLE:
        raise RuntimeError("FlexMessage not available")

    bubble = FlexBubble(
        body=FlexBox(
            layout="vertical",
            contents=[
                FlexText(text="友だちに紹介", weight="bold", size="xl"),
                FlexSeparator(margin="md"),
                FlexText(
                    text="このボタンから共有画面が開きます。\nLINEアプリ内でのご利用を推奨します。",
                    wrap=True,
                    size="sm",
                    margin="md",
                ),
            ],
            spacing="md"
        ),
        footer=FlexBox(
            layout="vertical",
            contents=[
                FlexButton(
                    style="primary",
                    height="md",
                    action=URIAction(label="LINEで紹介する", uri=liff_url),
                ),
            ],
            spacing="sm",
            margin="lg",
        ),
    )
    return FlexMessage(alt_text="友だちに紹介", contents=bubble)

def reply_share_message() -> List[Any]:
    """
    友だち紹介：Flexメッセージに差し替え（生URLをテキスト表示しない）
    Flex未対応/失敗時は最小限の案内のみ（URLは表示しない）
    """
    if LINE_SDK_AVAILABLE and FLEX_AVAILABLE:
        try:
            flex = build_share_flex()
            return [flex]
        except Exception as e:
            logger.warning(f"Flex build failed, fallback to plain notice: {e}")

    # フォールバック（URLは出さない）
    return [TextMessage(text="共有画面を開けませんでした。時間を置いてもう一度お試しください。")]

# ======================================================================
# 軽量重複防止（連打/再送対策）
# ======================================================================

class DuplicateGuard:
    def __init__(self):
        self.recent_events: Dict[str, float] = {}
        self.window = 6.0

    def seen(self, user_id: str, token: str) -> bool:
        now = time.time()
        key = f"{user_id}:{hashlib.md5(token.encode()).hexdigest()[:8]}"
        t = self.recent_events.get(key)
        self.recent_events[key] = now
        if len(self.recent_events) > 512:
            cutoff = now - self.window * 2
            for k, ts in list(self.recent_events.items()):
                if ts < cutoff:
                    self.recent_events.pop(k, None)
        return t is not None and (now - t) < self.window


dup_guard = DuplicateGuard()

# ======================================================================
# セッション管理（AI相談 / 資金計画）
# ======================================================================

class SessionStore:
    def __init__(self, ttl_seconds: int = 1800):
        self.ttl = ttl_seconds
        self.store: Dict[str, Dict[str, Any]] = {}

    def set_mode(self, user_id: str, mode: str):
        self.store[user_id] = {"mode": mode, "exp": time.time() + self.ttl}

    def get_mode(self, user_id: str) -> str:
        d = self.store.get(user_id)
        if not d:
            return ""
        if d["exp"] < time.time():
            self.store.pop(user_id, None)
            return ""
        return d.get("mode", "")


sessions = SessionStore(SESSION_TTL)

# ======================================================================
# LINE クライアント（キャッシュ再利用）
# ======================================================================

def _get_line_tokens() -> Tuple[str, str]:
    access_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
    channel_secret = os.getenv("LINE_CHANNEL_SECRET", "")
    if (not access_token or not channel_secret) and os.getenv("GOOGLE_CLOUD_PROJECT"):
        try:  # GCP Secret Manager
            from google.cloud import secretmanager

            sm = secretmanager.SecretManagerServiceClient()
            proj = os.getenv("GOOGLE_CLOUD_PROJECT")
            if not access_token:
                name = f"projects/{proj}/secrets/LINE_CHANNEL_ACCESS_TOKEN/versions/latest"
                access_token = sm.access_secret_version(request={"name": name}).payload.data.decode("utf-8")
            if not channel_secret:
                name = f"projects/{proj}/secrets/LINE_CHANNEL_SECRET/versions/latest"
                channel_secret = sm.access_secret_version(request={"name": name}).payload.data.decode("utf-8")
        except Exception as e:  # pragma: no cover
            logger.warning(f"SecretManager failed: {e}")
    return (access_token.strip(), channel_secret.strip())

try:
    from linebot.v3.messaging import Configuration, ApiClient, MessagingApi  # type: ignore
    configuration_cached: Optional["Configuration"] = None
    api_client_cached: Optional["ApiClient"] = None
    messaging_api_cached: Optional["MessagingApi"] = None
except Exception:  # pragma: no cover
    configuration_cached = api_client_cached = messaging_api_cached = None  # type: ignore

LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET = _get_line_tokens()
handler: Optional["WebhookHandler"] = None


def _ensure_api() -> Optional["MessagingApi"]:
    global configuration_cached, api_client_cached, messaging_api_cached
    try:
        if messaging_api_cached:
            return messaging_api_cached
        if not LINE_CHANNEL_ACCESS_TOKEN:
            return None
        configuration_cached = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
        api_client_cached = ApiClient(configuration_cached)
        messaging_api_cached = MessagingApi(api_client_cached)
        return messaging_api_cached
    except Exception as e:  # pragma: no cover
        logger.error(f"MessagingApi init failed: {e}")
        return None


if LINE_SDK_AVAILABLE and LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET:
    try:
        handler = WebhookHandler(LINE_CHANNEL_SECRET)
        _ensure_api()
        logger.info("✅ LINE handler initialized")
    except Exception as e:  # pragma: no cover
        logger.error(f"LINE handler init error: {e}")
        handler = None

# ======================================================================
# 送信ヘルパー
# ======================================================================

def _reply_or_push(reply_token: str, user_id: str, text: str) -> bool:
    api = _ensure_api()
    if not api:
        logger.error("MessagingApi not ready")
        return False
    if dup_guard.seen(user_id, f"out:{text[:64]}"):
        return True
    try:
        cleaned = _finalize_text(text)
        try:
            api.reply_message_with_http_info(
                ReplyMessageRequest(reply_token=reply_token, messages=[TextMessage(text=cleaned)])
            )
            return True
        except ApiException as e:
            if "Invalid reply token" in str(e) or getattr(e, "status", None) == 400:
                api.push_message_with_http_info(
                    PushMessageRequest(to=user_id, messages=[TextMessage(text=cleaned)])
                )
                return True
            logger.error(f"LINE reply failed: {e}")
            return False
    except Exception as e:
        logger.error(f"LINE send failed: {e}")
        return False


def _push(user_id: str, text: str) -> bool:
    api = _ensure_api()
    if not api:
        logger.error("MessagingApi not ready")
        return False
    if dup_guard.seen(user_id, f"out:{text[:64]}"):
        return True
    try:
        cleaned = _finalize_text(text)
        api.push_message_with_http_info(PushMessageRequest(to=user_id, messages=[TextMessage(text=cleaned)]))
        return True
    except Exception as e:
        logger.error(f"LINE push failed: {e}")
        return False


def _reply_or_push_flex(reply_token: str, user_id: str, flex: "FlexMessage") -> bool:
    api = _ensure_api()
    if not api:
        logger.error("MessagingApi not ready (flex)")
        return False
    if dup_guard.seen(user_id, f"flex:{getattr(flex, 'alt_text', 'consent')}"):
        return True
    try:
        try:
            api.reply_message_with_http_info(ReplyMessageRequest(reply_token=reply_token, messages=[flex]))
            return True
        except ApiException as e:
            if "Invalid reply token" in str(e) or getattr(e, "status", None) == 400:
                api.push_message_with_http_info(PushMessageRequest(to=user_id, messages=[flex]))
                return True
            logger.error(f"LINE flex reply failed: {e}")
            return False
    except Exception as e:  # pragma: no cover
        logger.error(f"LINE flex send failed: {e}")
        return False

# ======================================================================
# ユーザートークン処理 / 同意チェック / 同意 Flex
# ======================================================================

import httpx

PORT = os.getenv("PORT", "8080")
SELF_BASE = os.getenv("INTERNAL_BASE_URL", f"http://127.0.0.1:{PORT}")

def _extract_user_id_from_token(token: str) -> Optional[str]:
    if not token:
        return None
    if isinstance(token, str) and token.startswith("U") and 20 <= len(token) <= 64:
        return token
    try:
        import jwt

        payload = jwt.decode(token, options={"verify_signature": False}, algorithms=["HS256", "RS256", "ES256"])
        for field in ["sub", "user_id", "userId", "id"]:
            v = payload.get(field)
            if isinstance(v, str) and v:
                return v
    except Exception:
        pass
    if len(token) > 10:
        return token
    return None

def _is_line_uid(s: Optional[str]) -> bool:
    return isinstance(s, str) and s.startswith("U") and 20 <= len(s) <= 64

def _has_consent_sync(user_id: str) -> bool:
    try:
        headers = {"user_token": user_id, "X-User-Token": user_id}
        with httpx.Client(timeout=8.0) as client:
            r = client.post(
                f"{SELF_BASE}/consent/check", json={"user_id": user_id, "scope": "ai"}, headers=headers
            )
            if r.status_code == 200:
                data = r.json()
                return bool(data.get("valid") or data.get("is_valid"))
            else:
                logger.warning(f"Consent check failed: {r.status_code} {r.text}")
    except Exception as e:
        logger.warning(f"Consent check failed for {user_id[:8]}...: {e}")
    return False

def _make_consent_link(user_id: str, extra_qs: Dict[str, str] | None = None) -> str:
    q: Dict[str, str] = {}
    extra_qs = extra_qs or {
        "state": "line_ai",
        "utm_source": "line",
        "utm_medium": "richmenu",
        "utm_campaign": "ai_consult",
        "utm_content": "ai_menu",
    }
    for k in ["state", "ab", "utm_source", "utm_medium", "utm_campaign", "utm_content"]:
        v = extra_qs.get(k)
        if v:
            q[k] = v

    base = LIFF_CONSENT_URL or (f"{PUBLIC_BASE_URL}/liff/consent" if PUBLIC_BASE_URL else "/liff/consent")
    if base.startswith("/") and PUBLIC_BASE_URL:
        base = f"{PUBLIC_BASE_URL}{base}"
    return f"{base}?{urlencode(q)}" if q else base

def _not_consent_msg_for(user_id: str, extra_qs: Dict[str, str] | None = None) -> str:
    link = _make_consent_link(user_id, extra_qs)
    return (
        "ご利用前に同意が必要です。\n"
        "以下のボタンから同意ページを開いてください。\n\n"
        f"{link}"
    )

# Flex（同意）

def build_consent_flex(liff_url: str) -> "FlexMessage":
    if not FLEX_AVAILABLE:
        raise RuntimeError("FlexMessage not available")
    bubble = FlexBubble(
        body=FlexBox(
            layout="vertical",
            spacing="md",
            contents=[
                FlexText(text="AI相談のご利用前の同意", weight="bold", size="lg"),
                FlexText(
                    text="以下を確認のうえ「同意して開始」を押してください。",
                    wrap=True,
                    size="sm",
                    color="#555555",
                ),
                FlexSeparator(),
                # ✅ ここを 9 項目に拡張（UIレイアウトはそのまま）
                FlexBox(
                    layout="vertical",
                    spacing="sm",
                    margin="md",
                    contents=[
                        FlexText(text="・プライバシーポリシー / 利用規約", size="sm", wrap=True),
                        FlexText(text="・入力が外部サービスへ送信される場合あり", size="sm", wrap=True),
                        FlexText(text="・AIの課題・限界の理解", size="sm", wrap=True),
                        FlexText(text="・Cookie等の利用（任意）", size="sm", wrap=True),
                        FlexText(text="・AI に個人情報は入力しないでください", size="sm", wrap=True),
                        FlexText(text="・この AI は住宅検討の参考用に設計された自動応答です", size="sm", wrap=True),
                        FlexText(text="・AI の回答は必ずしも正しいとは限りません。→ 確定案内はスタッフが行います", size="sm", wrap=True),
                        FlexText(text="・ご質問の内容により、AI の回答までお時間を頂戴する場合がございます", size="sm", wrap=True),
                        FlexText(text="・ご使用の前に、必ず同意が必要となります。何卒ご理解賜りますようお願い申し上げます", size="sm", wrap=True),
                    ],
                ),
                FlexSeparator(),
                FlexButton(style="primary", height="sm", action=URIAction(label="同意して開始", uri=liff_url)),
            ],
        ),
    )
    return FlexMessage(alt_text="AI相談のご利用前の同意", contents=bubble)

# ======================================================================
# バックグラウンドワーカー
# ======================================================================

def _worker_finance(user_id: str, user_text: str):
    try:
        run_financial_plan = _resolve_financial_if_needed()
        if run_financial_plan is None:
            _push(user_id, "資金診断を準備中です。時間をおいてお試しください。")
            return
        import inspect, asyncio

        result = (
            asyncio.run(run_financial_plan(user_text))
            if inspect.iscoroutinefunction(run_financial_plan)
            else run_financial_plan(user_text)
        )
        _push(user_id, result or "結果を作成できませんでした。")
    except Exception as e:
        logger.error(f"_worker_finance fatal: {e}")

def _worker_ai(user_id: str, user_text: str):
    try:
        rag_fn = _resolve_rag_if_needed()
        if rag_fn is None:
            _push(user_id, "AI相談の準備中です。時間をおいてお試しください。")
            return
        try:
            answer, _ = rag_fn(user_text)
        except Exception as e:
            logger.error(f"RAG error: {e}")
            answer = "該当情報が見つかりませんでした。別の聞き方でお試しください。"
        _push(user_id, answer or "回答を作成できませんでした。")
    except Exception as e:
        logger.error(f"_worker_ai fatal: {e}")

# ======================================================================
# Webhook（**常に 200 で ACK**）
# ======================================================================

@router.post("/line/webhook")
@router.post("/webhook")
async def line_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        body = await request.body()
        signature = request.headers.get("X-Line-Signature") or request.headers.get("x-line-signature") or ""
        if handler:
            background_tasks.add_task(handler.handle, body.decode("utf-8"), signature)
        return JSONResponse({"status": "ok", "ts": datetime.now().isoformat()})
    except Exception as e:
        logger.error(f"webhook error: {e}")
        return JSONResponse({"status": "ok", "note": "handled with error"}, status_code=200)

# ======================================================================
# Postback data の堅牢パーサ
# ======================================================================

def _resolve_postback_key(data: str) -> str:
    """複数フォーマットの postback.data を 既存テンプレのキーへ正規化"""
    if not data:
        return ""

    # 1) そのまま一致
    if data in RICHMENU_FIXED_RESPONSES:
        return data
    if data in RICHMENU_KEYWORD_MAPPING:
        return RICHMENU_KEYWORD_MAPPING[data]

    # 友だち紹介（action=share）を先に判定
    if "action=share" in data.lower():
        return "__share__"

    # 2) JSON なら action / key / menu を探す
    if data.startswith("{") and data.endswith("}"):
        try:
            obj = json.loads(data)
            for k in ("action", "key", "menu"):
                v = obj.get(k)
                if isinstance(v, str) and v:
                    if v in RICHMENU_KEYWORD_MAPPING:
                        return RICHMENU_KEYWORD_MAPPING[v]
                    if v in RICHMENU_FIXED_RESPONSES:
                        return v
        except Exception:
            pass

    # 3) クエリ/セミコロン区切り
    for sep in ("&", ";"):
        if sep in data or "=" in data:
            parts = [p for p in data.split(sep) if p]
            for part in parts:
                if "=" in part:
                    k, v = part.split("=", 1)
                    v = v.strip()
                    if k.lower() == "action" and v.lower() == "share":
                        return "__share__"
                    if v in RICHMENU_KEYWORD_MAPPING:
                        return RICHMENU_KEYWORD_MAPPING[v]
                    if v in RICHMENU_FIXED_RESPONSES:
                        return v
                else:
                    token = part.strip()
                    if token in RICHMENU_KEYWORD_MAPPING:
                        return RICHMENU_KEYWORD_MAPPING[token]
                    if token in RICHMENU_FIXED_RESPONSES:
                        return token
            break

    token = data.strip()
    if token in RICHMENU_KEYWORD_MAPPING:
        return RICHMENU_KEYWORD_MAPPING[token]
    if token in RICHMENU_FIXED_RESPONSES:
        return token
    return ""

# ======================================================================
# イベントハンドラ（reply→push 方針）—— AI相談だけ同意ゲート
# ======================================================================

if LINE_SDK_AVAILABLE and handler:

    @handler.add(FollowEvent)
    def on_follow(event):
        try:
            user_id = event.source.user_id
            if dup_guard.seen(user_id, f"follow:{user_id}"):
                return
            _reply_or_push(event.reply_token, user_id, RICHMENU_FIXED_RESPONSES["follow_greeting"])
        except Exception as e:
            logger.error(f"follow handler error: {e}")

    @handler.add(MessageEvent, message=TextMessageContent)
    def on_message(event):
        try:
            user_id = event.source.user_id
            text = (event.message.text or "").strip()
            reply_token = event.reply_token
            if dup_guard.seen(user_id, f"in:{text[:64]}"):
                return

            # 友だち紹介（テキスト運用時のゆらぎ吸収）
            if _key(text) in SHARE_KEYS:
                msgs = reply_share_message()
                api = _ensure_api()
                if api:
                    try:
                        api.reply_message_with_http_info(ReplyMessageRequest(reply_token=reply_token, messages=msgs))
                    except ApiException:
                        api.push_message_with_http_info(PushMessageRequest(to=user_id, messages=msgs))
                return

            # リッチメニューのキーワード解決（文言は変更しない）
            key = None
            if text in RICHMENU_FIXED_RESPONSES:
                key = text
            else:
                for k, mapped in RICHMENU_KEYWORD_MAPPING.items():
                    if k in text:
                        key = mapped
                        break

            if key:
                # ★ AI相談/住まいAI相談 → 同意ゲートあり
                if key in ("AI相談", "住まいAI相談"):
                    if not _has_consent_sync(user_id):
                        liff_url = _make_consent_link(user_id)
                        if FLEX_AVAILABLE:
                            try:
                                flex_msg = build_consent_flex(liff_url)
                                if not _reply_or_push_flex(reply_token, user_id, flex_msg):
                                    _reply_or_push(reply_token, user_id, _not_consent_msg_for(user_id))
                            except Exception as e:
                                logger.error(f"Flex build/send error: {e}")
                                _reply_or_push(reply_token, user_id, _not_consent_msg_for(user_id))
                        else:
                            _reply_or_push(reply_token, user_id, _not_consent_msg_for(user_id))
                        return
                    sessions.set_mode(user_id, "ai")
                    _reply_or_push(reply_token, user_id, RICHMENU_FIXED_RESPONSES["住まいAI相談"])
                    return

                # ★ ここから追加：その他のメニューはそのまま返信（同意ゲートなし）
                elif key in ("住まいAIサイト", "資料請求", "展示場来場予約", "チャット相談"):
                    _reply_or_push(reply_token, user_id, RICHMENU_FIXED_RESPONSES[key])
                    return

                elif key == "資金計画":
                    sessions.set_mode(user_id, "finance")
                    _reply_or_push(reply_token, user_id, "📊 資金診断を開始します。気になる条件を入力してください。")
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

            # フォールバック
            fallback = (
                "ご質問ありがとうございます😊\n\n"
                "目的のボタンをタップしてください👇\n"
                "🤖AI相談 / 📍来場予約 / 📋資料請求 / 🌐サイト / 💬チャット\n\n"
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
            if dup_guard.seen(user_id, f"post:{data[:64]}"):
                return

            key = _resolve_postback_key(data)

            # 友だち紹介（推奨：Postback action=share）
            if key == "__share__":
                msgs = reply_share_message()
                api = _ensure_api()
                if api:
                    try:
                        api.reply_message_with_http_info(ReplyMessageRequest(reply_token=reply_token, messages=msgs))
                    except ApiException:
                        api.push_message_with_http_info(PushMessageRequest(to=user_id, messages=msgs))
                return

            if key:
                # ★ AI相談/住まいAI相談 → 同意ゲートあり
                if key in ("AI相談", "住まいAI相談"):
                    if not _has_consent_sync(user_id):
                        liff_url = _make_consent_link(user_id)
                        if FLEX_AVAILABLE:
                            try:
                                flex_msg = build_consent_flex(liff_url)
                                if not _reply_or_push_flex(reply_token, user_id, flex_msg):
                                    _reply_or_push(reply_token, user_id, _not_consent_msg_for(user_id))
                            except Exception as e:
                                logger.error(f"Postback flex error: {e}")
                                _reply_or_push(reply_token, user_id, _not_consent_msg_for(user_id))
                        else:
                            _reply_or_push(reply_token, user_id, _not_consent_msg_for(user_id))
                        return
                    sessions.set_mode(user_id, "ai")
                    _reply_or_push(reply_token, user_id, RICHMENU_FIXED_RESPONSES["住まいAI相談"])
                    return

                # ★ ここから追加：その他のメニューはそのまま返信（同意ゲートなし）
                elif key in ("住まいAIサイト", "資料請求", "展示場来場予約", "チャット相談"):
                    _reply_or_push(reply_token, user_id, RICHMENU_FIXED_RESPONSES[key])
                    return

                elif key == "資金計画":
                    sessions.set_mode(user_id, "finance")
                    _reply_or_push(reply_token, user_id, "📊 資金診断を開始します。気になる条件を入力してください。")
                    return

            _reply_or_push(
                reply_token,
                user_id,
                "目的のボタンをタップしてください😊\n\n🤖AI相談 / 📍来場予約 / 📋資料請求 / 🌐サイト / 💬チャット",
            )
        except Exception as e:
            logger.error(f"postback handler error: {e}")

# ======================================================================
# 同意完了後のプッシュ（AI相談を自動開始）— UID最優先
# ======================================================================

class ConsentPayload(BaseModel):
    user_token: str
    consent: bool = True
    utm: dict | None = None

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
        user_token = (
            (payload or {}).get("user_token")
            or request.headers.get("X-User-Token")
            or request.headers.get("user_token")
            or ""
        )

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
        # ★ 修正：固定文言は「住まいAI相談」を使用（辞書に存在するキー）
        ok = _push(user_id, RICHMENU_FIXED_RESPONSES["住まいAI相談"])
        if ok:
            _push(
                user_id,
                "✅ 同意が完了しました！\n\nこれでAI相談をご利用いただけます。\n住まいに関するご質問をお気軽にどうぞ😊",
            )
            return JSONResponse(
                {
                    "ok": True,
                    "success": True,
                    "user_id_hash": hashlib.md5(user_id.encode()).hexdigest()[:8],
                    "session_mode": "ai",
                    "request_id": request_id,
                    "timestamp": datetime.now().isoformat(),
                },
                status_code=200,
            )
        else:
            logger.error(f"[{request_id}] push failed")
            return JSONResponse({"ok": False, "error": "push_failed", "request_id": request_id}, status_code=500)

    except Exception as e:
        logger.error(f"[{request_id}] after-consent unexpected: {e}")
        logger.error(traceback.format_exc())
        return JSONResponse(
            {
                "ok": False,
                "error": "internal_error",
                "detail": str(e),
                "request_id": request_id,
                "timestamp": datetime.now().isoformat(),
            },
            status_code=500,
        )

@router.post("/line/consent", tags=["liff"], status_code=204)
async def record_consent(payload: ConsentPayload) -> Response:  # まずは 204 を返すだけ
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
    from linebot.v3.messaging import MessagingApi  # type: ignore

    def _ready() -> bool:
        try:
            return bool(LINE_SDK_AVAILABLE and handler and isinstance(_ensure_api(), MessagingApi))
        except Exception:
            return False

    return {
        "status": "ok" if _ready() else "degraded",
        "ts": datetime.now().isoformat(),
        "timeout": LINE_RESPONSE_TIMEOUT,
        "share_url": _share_url(),
    }
