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

    # 「【出典】…」のようなブロック以降を削る
    text = re.sub(r"【\s*(出典|参考|資料)\s*】[\s\S]*?$", "", text, flags=re.MULTILINE)

    # (p.12) / (p. 12) / (p:12) / (p：12) / (p.?) / （p.？） など
    # 半角/全角かっこ・?と全角？に対応。文中どこでも除去。
    text = re.sub(r"[（(]\s*[pP]\s*[\.\:：]?\s*(\d+|[?？]+)\s*[)）]", "", text)

    # 連続改行の整形
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text

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
    "follow_greeting": """こんにちは！キノエデザイン住まいAIプランナー（秋山住研）です。
この度は友だち追加ありがとうございます✨
まずはメニュー左上の「AI相談（24h）」から、 気になることを質問してみてください。


すぐ使えるメニューはこちら👇
🤖AI相談 / 📍来場予約 / 📄資料請求 / 💴資金計画 / 🌐サイト / 💬チャット


※匿名OK／保存OFF（既定）
※AIの回答は必ずしも正しいとは限りません。➡ 最終案内はスタッフが行います。
※AIは24時間、担当者は当日〜翌営業日に返信します。
※ご使用の前に、必ず以下の取り扱いをご確認ください。
プライバシーポリシー：【https://ai.kinoedesign.co.jp/privacy-policy 】
利用規約：【https://ai.kinoedesign.co.jp/termsofuse/service 】
Cookie：【https://ai.kinoedesign.co.jp/cookie 】""",

    "AI相談": """🤖 AI住まい相談を開始します！
キノエデザインの住まいAIプランナーです。
住まいに関するご質問をお気軽にどうぞ！
💡 **例えば**
・坪単価について教えて
・標準仕様はどんな感じ？
・耐震性能について知りたい
・断熱性能はどのくらい？
何でもお聞きください😊


→ ＜AI相談（24h）＞
※ AIの回答は必ずしも正しいとは限りません。→ 確定案内はスタッフが行います。
※ご質問の内容により、AIの回答までお時間を頂戴する場合がございます。何卒ご理解賜りますようお願い申し上げます。
※ご使用の前に、必ず以下の取り扱いをご確認ください。
プライバシーポリシー：【https://ai.kinoedesign.co.jp/privacy-policy 】
利用規約：【https://ai.kinoedesign.co.jp/termsofuse/service 】
Cookie：【https://ai.kinoedesign.co.jp/cookie 】""",

    "AI住まいサイト": """🌐 AI住まいサイトのご案内
キノエデザインの住まい情報サイトをご紹介します。（家づくりの疑問にAIが24時間即回答）
🏠
回遊動線／資金目安／土地・学区／性能・保証など、 気になることや、お悩みを AI が、お答え解決するホームページです。
ZINE、ダウンロードもできます。


※ 匿名OK／保存OFF（既定）
※ AIの回答は必ずしも正しいとは限りません。 → 最終案内はスタッフが行います。
📱 サイトURL：
https://ai.kinoedesign.co.jp/""",

    "資料請求": """📋ありがとうございます！
下記のリンクより、資料をご請求ください。
リンク：https://kinoedesign.co.jp/request/""",

    "展示場来場予約": """📍 展示場のご来場予約:
24 時間いつでも、予約OKです。
ご予約の際は、下記の来場予約ホームページURLよりご送信ください。：

来場予約ホームページURL：
【https://kinoedesign.co.jp/consultation/ 】""",

    "資金計画": """💬 AI資金診断のご案内
本診断は匿名でご利用いただけます。
ご回答内容は保存いたしません。
算出される金額は試算（概算）であり、目安としてご確認ください。
お手数ですが、以下の項目をご入力ください。

・世帯年収（合算の有無）：
・頭金（自己資金）：
・返済期間（年数）：
・想定金利：
・他の借入の毎月返済額合計（車・カード・教育ローン等):
・借入時の年齢：

未入力の項目があっても進められます。
ご入力後、概算結果をご提示いたします。
※ 結果は概算です → 詳細はスタッフがご案内します。
※ AIの回答は必ずしも正しいとは限りません。→ 確定案内はスタッフが行います。
※ご使用の前に、必ず以下の取り扱いをご確認ください。
プライバシーポリシー：【https://ai.kinoedesign.co.jp/privacy-policy 】
利用規約：【https://ai.kinoedesign.co.jp/termsofuse/service 】
Cookie：【https://ai.kinoedesign.co.jp/cookie 】""",

    "チャット相談": """💬 スタッフとのご相談
AI より、人の方がいい方はこちら
スタッフとチャット相談。
お気軽にメッセージどうぞ！

【対応時間】
営業時間：9:00-18:00

📱 ご相談方法：
・このLINEでの直接チャット相談
・お電話での相談
・展示場での対面相談

📱 ご相談内容：
・住まいづくり全般
・土地探し
・資金計画
・間取り
・デザイン
・住宅性能について など

営業時間内でしたら迅速にお返事します。
お気軽にお声かけください！""",
}

RICHMENU_KEYWORD_MAPPING: Dict[str, str] = {
    "AI相談": "AI相談", ":robot: AI相談": "AI相談", "🤖 AI相談": "AI相談",
    "AI住まいサイト": "AI住まいサイト", "🌐 AI住まいサイト": "AI住まいサイト", "サイト": "AI住まいサイト", "ホームページ": "AI住まいサイト",
    "資料請求": "資料請求", "📋 資料請求": "資料請求",
    "展示場来場予約": "展示場来場予約", "📍 展示場来場　予約": "展示場来場予約", "来場予約": "展示場来場予約",
    "資金計画": "資金計画", "💴 資金計画": "資金計画", "💰 資金計画": "資金計画",
    "チャット相談": "チャット相談", "💬チャット相談": "チャット相談", "チャット": "チャット相談",
    # 可能性のある英語/シンプルdata対策
    "ai_consult": "AI相談", "site": "AI住まいサイト", "docs": "資料請求",
    "reservation": "展示場来場予約", "finance": "資金計画", "chat": "チャット相談",
}

# ======================================================================
# 軽量重複防止（連打/再送対策）
# ======================================================================
class DuplicateGuard:
    def __init__(self): self.recent_events: Dict[str, float] = {}; self.window = 6.0
    def seen(self, user_id: str, token: str) -> bool:
        now = time.time(); key = f"{user_id}:{hashlib.md5(token.encode()).hexdigest()[:8]}"; t = self.recent_events.get(key)
        self.recent_events[key] = now
        if len(self.recent_events) > 512:
            cutoff = now - self.window * 2
            for k, ts in list(self.recent_events.items()):
                if ts < cutoff: self.recent_events.pop(k, None)
        return t is not None and (now - t) < self.window

dup_guard = DuplicateGuard()

# ======================================================================
# セッション管理（AI相談 / 資金計画）
# ======================================================================
class SessionStore:
    def __init__(self, ttl_seconds: int = 1800):
        self.ttl = ttl_seconds; self.store: Dict[str, Dict[str, Any]] = {}
    def set_mode(self, user_id: str, mode: str): self.store[user_id] = {"mode": mode, "exp": time.time() + self.ttl}
    def get_mode(self, user_id: str) -> str:
        d = self.store.get(user_id)
        if not d: return ""
        if d["exp"] < time.time(): self.store.pop(user_id, None); return ""
        return d.get("mode", "")

sessions = SessionStore(SESSION_TTL)

# ======================================================================
# LINE クライアント（キャッシュ再利用）
# ======================================================================
def _get_line_tokens() -> Tuple[str, str]:
    access_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
    channel_secret = os.getenv("LINE_CHANNEL_SECRET", "")
    if (not access_token or not channel_secret) and os.getenv("GOOGLE_CLOUD_PROJECT"):
        try:
            from google.cloud import secretmanager
            sm = secretmanager.SecretManagerServiceClient()
            proj = os.getenv("GOOGLE_CLOUD_PROJECT")
            if not access_token:
                name = f"projects/{proj}/secrets/LINE_CHANNEL_ACCESS_TOKEN/versions/latest"
                access_token = sm.access_secret_version(request={"name": name}).payload.data.decode("utf-8")
            if not channel_secret:
                name = f"projects/{proj}/secrets/LINE_CHANNEL_SECRET/versions/latest"
                channel_secret = sm.access_secret_version(request={"name": name}).payload.data.decode("utf-8")
        except Exception as e:
            logger.warning(f"SecretManager failed: {e}")
    return (access_token.strip(), channel_secret.strip())

try:
    from linebot.v3.messaging import Configuration, ApiClient, MessagingApi  # type: ignore
    configuration_cached: Optional["Configuration"] = None
    api_client_cached: Optional["ApiClient"] = None
    messaging_api_cached: Optional["MessagingApi"] = None
except Exception:
    configuration_cached = api_client_cached = messaging_api_cached = None  # type: ignore

LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET = _get_line_tokens()
handler: Optional["WebhookHandler"] = None

def _ensure_api() -> Optional["MessagingApi"]:
    global configuration_cached, api_client_cached, messaging_api_cached
    try:
        if messaging_api_cached: return messaging_api_cached
        if not LINE_CHANNEL_ACCESS_TOKEN: return None
        configuration_cached = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
        api_client_cached = ApiClient(configuration_cached)
        messaging_api_cached = MessagingApi(api_client_cached)
        return messaging_api_cached
    except Exception as e:
        logger.error(f"MessagingApi init failed: {e}"); return None

if LINE_SDK_AVAILABLE and LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET:
    try:
        handler = WebhookHandler(LINE_CHANNEL_SECRET); _ensure_api()
        logger.info("✅ LINE handler initialized")
    except Exception as e:
        logger.error(f"LINE handler init error: {e}"); handler = None

# ======================================================================
# 送信ヘルパー（テキスト）
# ======================================================================
def _reply_or_push(reply_token: str, user_id: str, text: str) -> bool:
    api = _ensure_api()
    if not api: logger.error("MessagingApi not ready"); return False
    if dup_guard.seen(user_id, f"out:{text[:64]}"): return True
    try:
        cleaned = _strip_citations(text or "")
        try:
            api.reply_message_with_http_info(ReplyMessageRequest(reply_token=reply_token, messages=[TextMessage(text=cleaned)]))
            return True
        except ApiException as e:
            if "Invalid reply token" in str(e) or getattr(e, "status", None) == 400:
                api.push_message_with_http_info(PushMessageRequest(to=user_id, messages=[TextMessage(text=cleaned)])); return True
            logger.error(f"LINE reply failed: {e}"); return False
    except Exception as e:
        logger.error(f"LINE send failed: {e}"); return False

def _push(user_id: str, text: str) -> bool:
    api = _ensure_api()
    if not api: logger.error("MessagingApi not ready"); return False
    if dup_guard.seen(user_id, f"out:{text[:64]}"): return True
    try:
        cleaned = _strip_citations(text or "")
        api.push_message_with_http_info(PushMessageRequest(to=user_id, messages=[TextMessage(text=cleaned)])); return True
    except Exception as e:
        logger.error(f"LINE push failed: {e}"); return False

# ======================================================================
# 送信ヘルパー（Flex）
# ======================================================================
def _reply_or_push_flex(reply_token: str, user_id: str, flex: "FlexMessage") -> bool:
    api = _ensure_api()
    if not api:
        logger.error("MessagingApi not ready (flex)")
        return False
    # 重複防止キーは alt_text のみで十分（リンクは本文に含めない）
    if dup_guard.seen(user_id, f"flex:{getattr(flex, 'alt_text', 'consent')}"):
        return True
    try:
        try:
            api.reply_message_with_http_info(ReplyMessageRequest(reply_token=reply_token, messages=[flex]))
            return True
        except ApiException as e:
            if "Invalid reply token" in str(e) or getattr(e, "status", None) == 400:
                api.push_message_with_http_info(PushMessageRequest(to=user_id, messages=[flex])); return True
            logger.error(f"LINE flex reply failed: {e}")
            return False
    except Exception as e:
        logger.error(f"LINE flex send failed: {e}")
        return False

# ======================================================================
# ユーザートークン処理（修正版）
# ======================================================================
def _extract_user_id_from_token(token: str) -> Optional[str]:
    """トークンからユーザーIDを抽出（改善版）"""
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

# ======================================================================
# 同意チェック（AI相談の時だけ使う）- 修正版
# ======================================================================
import httpx
PORT = os.getenv("PORT", "8080")
SELF_BASE = os.getenv("INTERNAL_BASE_URL", f"http://127.0.0.1:{PORT}")

def _has_consent_sync(user_id: str) -> bool:
    """同意チェック（改善版）"""
    try:
        headers = {"user_token": user_id, "X-User-Token": user_id}
        with httpx.Client(timeout=8.0) as client:
            r = client.post(f"{SELF_BASE}/consent/check",
                            json={"user_id": user_id, "scope": "ai"},
                            headers=headers)
            if r.status_code == 200:
                data = r.json()
                return bool(data.get("valid") or data.get("is_valid"))
            else:
                logger.warning(f"Consent check failed: {r.status_code} {r.text}")
    except Exception as e:
        logger.warning(f"Consent check failed for {user_id[:8]}...: {e}")
    return False

# --- ユーザー別「同意リンク」生成（/liff/consent）---
def _make_consent_link(user_id: str, extra_qs: Dict[str, str] | None = None) -> str:
    """
    LIFF の完全URL（LIFF_CONSENT_URL）を最優先で使用。
    無い場合は PUBLIC_BASE_URL(/liff/consent) を使用。
    ★ user_token は URL に含めない（LIFF SDK から直接取得）
    """
    q = {}
    if not extra_qs:
        extra_qs = {
            "state": "line_ai",
            "utm_source": "line",
            "utm_medium": "richmenu",
            "utm_campaign": "ai_consult",
            "utm_content": "ai_menu",
        }
    for k in ["state", "ab", "utm_source", "utm_medium", "utm_campaign", "utm_content"]:
        v = extra_qs.get(k) if extra_qs else None
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

# ======================================================================
# 同意 Flex のビルダー（正しいFlexBubble構造）
# ======================================================================
def build_consent_flex(liff_url: str) -> "FlexMessage":
    """同意用のFlexメッセージを作成（修正版）"""
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
                    color="#555555"
                ),
                FlexSeparator(),
                FlexBox(
                    layout="vertical",
                    spacing="sm",
                    margin="md",
                    contents=[
                        FlexText(text="・プライバシーポリシー / 利用規約", size="sm", wrap=True),
                        FlexText(text="・入力が外部サービスへ送信される場合あり", size="sm", wrap=True),
                        FlexText(text="・AIの誤答・限界の理解", size="sm", wrap=True),
                        FlexText(text="・Cookie等の利用（任意）", size="sm", wrap=True),
                    ],
                ),
                FlexSeparator(),
                FlexButton(
                    style="primary",
                    height="sm",
                    action=URIAction(label="同意して開始", uri=liff_url),
                ),
            ],
        ),
    )
    return FlexMessage(alt_text="AI相談のご利用前の同意", contents=bubble)

# ======================================================================
# バックグラウンド・ワーカー
# ======================================================================
def _worker_finance(user_id: str, user_text: str):
    try:
        run_financial_plan = _resolve_financial_if_needed()
        if run_financial_plan is None:
            _push(user_id, "資金診断を準備中です。時間をおいてお試しください。"); return
        import inspect, asyncio
        result = asyncio.run(run_financial_plan(user_text)) if inspect.iscoroutinefunction(run_financial_plan) else run_financial_plan(user_text)
        _push(user_id, _strip_citations(result or "").strip() or "結果を作成できませんでした。")
    except Exception as e:
        logger.error(f"_worker_finance fatal: {e}")

def _worker_ai(user_id: str, user_text: str):
    try:
        rag_fn = _resolve_rag_if_needed()
        if rag_fn is None:
            _push(user_id, "AI相談の準備中です。時間をおいてお試しください。"); return
        try:
            answer, _ = rag_fn(user_text)
        except Exception as e:
            logger.error(f"RAG error: {e}"); answer = "該当情報が見つかりませんでした。別の聞き方でお試しください。"
        _push(user_id, _strip_citations(answer or "").strip() or "回答を作成できませんでした。")
    except Exception as e:
        logger.error(f"_worker_ai fatal: {e}")

# ======================================================================
# Webhook（**常に 200 で ACK**）
# ======================================================================
@router.post("/line/webhook")
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
    """
    data の形：
      - "action=AI相談&..." などのクエリ
      - "ai_consult" のようなプレーン文字列
      - '{"action":"AI相談"}' のようなJSON
    をすべて許容して「固定テンプレのキー」を返す
    """
    if not data:
        return ""

    # 1) そのまま一致
    if data in RICHMENU_FIXED_RESPONSES:
        return data
    if data in RICHMENU_KEYWORD_MAPPING:
        return RICHMENU_KEYWORD_MAPPING[data]

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

    # 3) クエリ/セミコロン区切りを解析
    for sep in ("&", ";"):
        if sep in data or "=" in data:
            parts = [p for p in data.split(sep) if p]
            for part in parts:
                if "=" in part:
                    k, v = part.split("=", 1)
                    v = v.strip()
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

    # 4) 最後にプレーン文字列として再チェック
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
    from linebot.v3.webhooks import MessageEvent, TextMessageContent, PostbackEvent, FollowEvent

    @handler.add(FollowEvent)
    def on_follow(event):
        try:
            user_id = event.source.user_id
            if dup_guard.seen(user_id, f"follow:{user_id}"): return
            _reply_or_push(event.reply_token, user_id, RICHMENU_FIXED_RESPONSES["follow_greeting"])
        except Exception as e:
            logger.error(f"follow handler error: {e}")

    @handler.add(MessageEvent, message=TextMessageContent)
    def on_message(event):
        try:
            user_id = event.source.user_id
            text = (event.message.text or "").strip()
            reply_token = event.reply_token
            if dup_guard.seen(user_id, f"in:{text[:64]}"): return

            # リッチメニューのキーワード解決（文面は変更しない）
            key = None
            if text in RICHMENU_FIXED_RESPONSES:
                key = text
            else:
                for k, mapped in RICHMENU_KEYWORD_MAPPING.items():
                    if k in text:
                        key = mapped
                        break

            # リッチメニュー項目にヒット
            if key:
                if key == "AI相談":
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
                _reply_or_push(reply_token, user_id, RICHMENU_FIXED_RESPONSES[key]); return

            # モードに応じて振り分け
            mode = sessions.get_mode(user_id)
            if mode == "finance":
                _reply_or_push(reply_token, user_id, "📊 試算中です。少しお待ちください…")
                threading.Thread(target=_worker_finance, args=(user_id, text), daemon=True).start(); return
            if mode == "ai":
                _reply_or_push(reply_token, user_id, "🔎 少しお待ちください…")
                threading.Thread(target=_worker_ai, args=(user_id, text), daemon=True).start(); return

            # どれにも該当しない通常テキストへのフォールバック
            fallback = (
                "ご質問ありがとうございます😊\n\n"
                "目的のボタンをタップしてください👇\n"
                ":robot:AI相談 / :round_pushpin:来場予約 / :page_facing_up:資料請求 / :yen:資金計画 / :globe_with_meridians:サイト / :speech_balloon:チャット\n\n"
                "具体的なご質問もお気軽にどうぞ:sparkles:"
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
                if key == "AI相談":
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
                _reply_or_push(reply_token, user_id, RICHMENU_FIXED_RESPONSES[key]); return

            _reply_or_push(
                reply_token, user_id,
                "目的のボタンをタップしてください😊\n\n:robot:AI相談 / :round_pushpin:来場予約 / :page_facing_up:資料請求 / :yen:資金計画 / :globe_with_meridians:サイト / :speech_balloon:チャット",
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
        ok = _push(user_id, RICHMENU_FIXED_RESPONSES["AI相談"])
        if ok:
            _push(user_id, "✅ 同意が完了しました！\n\nこれでAI相談をご利用いただけます。\n住まいに関するご質問をお気軽にどうぞ😊")
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