# api/routers/line_bot_ultra_fast.py — 同意ゲート入り・最終版 + Postback堅牢化
# - リッチメニューは6項目すべて反応（文面は変更しない）
# - 「AI相談」だけ /consent/check を叩き、未同意なら **ユーザー別** 同意URLを案内（完全URLで送付）
# - Webhook は常に 200 を返す（LINE の再送ループ防止）
# - RAG / 資金計画は別スレッドで push（応答遅延を防ぐ）
# - 同意保存後に /line/after-consent で AI相談を自動開始（Push）
# - Postback の data は action=..., クエリ形式, JSON, プレーン文字列 すべてに対応

import logging, os, re, time, hashlib, threading, sys, pathlib, importlib, json
from datetime import datetime
from typing import Dict, Optional, Any, Tuple
from urllib.parse import urlencode, urlparse, parse_qsl, urlunparse

from fastapi import APIRouter, Request, BackgroundTasks, Body
from fastapi.responses import JSONResponse

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
# 出典/参考/資料の文言は一切表示しない
# ======================================================================
def _strip_citations(text: str) -> str:
    if not text:
        return text
    text = re.sub(r"^\s*(参考|資料|出典)\s*[:：].*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"【出典】[\s\S]*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s*\(p\.\s*\d+\s*\)\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text

# ======================================================================
# LINE SDK v3（存在しない環境でも落ちないように）
# ======================================================================
try:
    from linebot.v3 import WebhookHandler
    from linebot.v3.messaging import (
        Configuration, ApiClient, MessagingApi,
        ReplyMessageRequest, PushMessageRequest, TextMessage, ApiException,
    )
    from linebot.v3.webhooks import MessageEvent, TextMessageContent, PostbackEvent, FollowEvent
    LINE_SDK_AVAILABLE = True
    logger.info("✅ LINE Bot SDK v3 imported")
except Exception as e:
    LINE_SDK_AVAILABLE = False
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
# 固定テンプレ（※リッチメニューの文面は変更しない）
# ======================================================================
RICHMENU_FIXED_RESPONSES: Dict[str, str] = {
    "follow_greeting": """こんにちは！キノエデザイン住まいAIコンシェルジュ（秋山住研）です。
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
Cookie：【https://preview.studio.site/live/EjOQljz1WJ/cookie 】""",

    "AI相談": """🤖 AI住まい相談を開始します！
キノエデザインの住まいAIコンシェルジュです。
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
プライバシーポリシー：【https://preview.studio.site/live/EjOQljz1WJ/privacy-policy 】
利用規約：【https://preview.studio.site/live/EjOQljz1WJ/termsofuse/service 】
Cookie：【https://preview.studio.site/live/EjOQljz1WJ/cookie 】""",

    "AI住まいサイト": """🌐 AI住まいサイトのご案内
キノエデザインの住まい情報サイトをご紹介します。（家づくりの疑問にAIが24時間即回答）
🏠
回遊動線／資金目安／土地・学区／性能・保証など、 気になることや、お悩みを AI が、お答え解決するホームページです。
ZINE、ダウンロードもできます。


※ 匿名OK／保存OFF（既定）
※ AIの回答は必ずしも正しいとは限りません。 → 最終案内はスタッフが行います。
📱 サイトURL：
https://preview.studio.site/live/EjOQljz1WJ/""",

    "資料請求": """📋ありがとうございます！こちらからご覧いただけます。
Web版と、カタログ版を選択できます


Web版 ご希望はこちら
サイトURL（LINE公式、ホームページ）： http//.aaa


カタログ郵送 ご希望はこちら
サイトURL（LINE公式、ホームページ）： http//.aaa


※必ず以下の取り扱いをご確認ください。
プライバシーポリシー：【https://preview.studio.site/live/EjOQljz1WJ/privacy-policy 】
利用規約：【https://preview.studio.site/live/EjOQljz1WJ/termsofuse/service 】
Cookie：【https://preview.studio.site/live/EjOQljz1WJ/cookie 】""",

    "展示場来場予約": """📍 展示場のご来場予約:
24 時間いつでも、予約OKです。
ご予約の際は、以下の内容をLINEのメッセージでお送りいただくか、下記の来場予約ホームページURLよりご送信ください。：


予約情報：
・ご希望日時（第１・第２希望）
・お名前 ・参加人数（大人・お子様）
・ご質問
・ご要望
※確定のご連絡は追って担当より差し上げます。
見学時間： 約90分
展示場： 最新の住宅仕様をご確認 スタッフ一同、心よりお待ちしております！ ご質問もお気軽にどうぞ。


来場予約ホームページURL：
【https://preview.studio.site/live/EjOQljz1WJ/reservation 】


※必ず以下の取り扱いをご確認ください。
プライバシーポリシー：【https://preview.studio.site/live/EjOQljz1WJ/privacy-policy 】
利用規約：【https://preview.studio.site/live/EjOQljz1WJ/termsofuse/service 】
Cookie：【https://preview.studio.site/live/EjOQljz1WJ/cookie 】""",

    "資金計画": """💬 AI資金診断のご案内
本診断は匿名でご利用いただけます。
ご回答内容は保存いたしません。
算出される金額は試算（概算）であり、目安としてご確認ください。
お手数ですが、以下の項目をご入力ください。
・年収：
・毎月のご希望返済額：
・住宅ローンのご希望借入期間：
・ご家族構成：（例：大人2名・お子さま1名）
・その他の大きなご負担：（例：自動車ローン 等）
・頭金：


未入力の項目があっても進められます。
ご入力後、概算結果をご提示いたします。
※ 結果は概算です → 詳細はスタッフがご案内します。""",

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
    # 可能性のある英語/シンプルdata対策（リッチメニューのdataが英語の場合）
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
# 送信ヘルパー
# ======================================================================
def _reply_or_push(reply_token: str, user_id: str, text: str) -> bool:
    api = _ensure_api()
    if not api: logger.error("MessagingApi not ready"); return False
    if dup_guard.seen(user_id, f"out:{text[:64]}"): return True
    try:
        try:
            api.reply_message_with_http_info(ReplyMessageRequest(reply_token=reply_token, messages=[TextMessage(text=text)]))
            return True
        except ApiException as e:
            if "Invalid reply token" in str(e) or getattr(e, "status", None) == 400:
                api.push_message_with_http_info(PushMessageRequest(to=user_id, messages=[TextMessage(text=text)])); return True
            logger.error(f"LINE reply failed: {e}"); return False
    except Exception as e:
        logger.error(f"LINE send failed: {e}"); return False

def _push(user_id: str, text: str) -> bool:
    api = _ensure_api()
    if not api: logger.error("MessagingApi not ready"); return False
    if dup_guard.seen(user_id, f"out:{text[:64]}"): return True
    try:
        api.push_message_with_http_info(PushMessageRequest(to=user_id, messages=[TextMessage(text=text)])); return True
    except Exception as e:
        logger.error(f"LINE push failed: {e}"); return False

# ======================================================================
# 同意チェック（AI相談の時だけ使う）
# ======================================================================
import httpx
PORT = os.getenv("PORT", "8080")
SELF_BASE = os.getenv("INTERNAL_BASE_URL", f"http://127.0.0.1:{PORT}")

def _has_consent_sync(user_id: str) -> bool:
    """ /consent/check を叩いて同意済みか確認（失敗時は False を返す＝安全側） """
    try:
        headers = {"user_token": user_id}  # consent API はヘッダでの受け取りに対応（front実装と合わせる）
        with httpx.Client(timeout=5.0) as client:
            # scope は "ai" を使用（キャッシュキー一貫性のため）
            r = client.post(f"{SELF_BASE}/consent/check", json={"scope": "ai"}, headers=headers)
            if r.status_code == 200:
                data = r.json()
                return bool(data.get("valid") or data.get("is_valid"))
    except Exception as e:
        logger.warning(f"consent check failed: {e}")
    return False

# --- ユーザー別「同意リンク」生成（/liff/consent） ---
def _make_consent_link(user_id: str, extra_qs: Dict[str, str] | None = None) -> str:
    """
    LIFF の完全URL（LIFF_CONSENT_URL）を最優先で使用。
    無い場合は PUBLIC_BASE_URL(/liff/consent) を使い、相対URLは返さない。
    """
    q = {"user_token": user_id}
    # ✅ デフォルトUTM（AI相談/LINEリッチメニュー流入をGA4で判別可能に）
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

    public_base = PUBLIC_BASE_URL
    base = ""
    if LIFF_CONSENT_URL:
        base = LIFF_CONSENT_URL
    elif public_base:
        base = f"{public_base}/liff/consent"
    else:
        base = "/liff/consent"  # 最低限のフォールバック

    # 相対であれば、可能なら public_base を付けて完全URL化
    if base.startswith("/") and public_base:
        base = f"{public_base}{base}"

    return f"{base}?{urlencode(q)}"

def _not_consent_msg_for(user_id: str, extra_qs: Dict[str, str] | None = None) -> str:
    link = _make_consent_link(user_id, extra_qs)
    return (
        "ご利用前に同意が必要です。\n"
        "以下のボタンから同意ページを開いてください。\n\n"
        f"{link}"
    )

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

    # 4) 最後にプレーン文字列として再チェック（大文字小文字&空白トリム）
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
                    # 未同意ならリンクを返して終了
                    if not _has_consent_sync(user_id):
                        _reply_or_push(reply_token, user_id, _not_consent_msg_for(user_id)); return
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
                        # Postback にもユーザー別同意リンクを返す
                        _reply_or_push(reply_token, user_id, _not_consent_msg_for(user_id)); return
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
# 同意完了後のプッシュ（AI相談を自動開始）
# ======================================================================
def _token_to_user_id(token: str) -> str:
    """LINE UID ならそのまま、JWTなら sub/user_id/email を拾う。未判定は token を返す。"""
    if token and token.startswith("U"):
        return token
    try:
        import jwt
        payload = jwt.decode(token, options={"verify_signature": False}, algorithms=["HS256", "RS256", "ES256"])
        return payload.get("sub") or payload.get("user_id") or payload.get("email") or token
    except Exception:
        return token

@router.post("/line/after-consent")
async def after_consent(payload: dict = Body(...)):
    user_token = (payload or {}).get("user_token", "")
    if not user_token:
        return {"ok": False, "error": "missing_user_token"}
    user_id = _token_to_user_id(user_token)
    try:
        sessions.set_mode(user_id, "ai")
        _push(user_id, RICHMENU_FIXED_RESPONSES["AI相談"])
        return {"ok": True}
    except Exception as e:
        logger.error(f"after_consent push failed: {e}")
        return {"ok": False, "error": "push_failed"}

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
