# api/routers/line_bot_ultra_fast.py — 完全修正版（lazy-load ＆ 即ACK ＆ push最終）
# - リッチメニュー押下は即時 reply（定型文）
# - RAG / 資金計画はバックグラウンドで実行 → push で最終結果
# - 「出典/参考/資料」等は非表示
# - Webhook は /line/webhook

import logging
import os
import re
import time
import hashlib
import threading
from datetime import datetime
from typing import Dict, Optional, Any, Tuple

from fastapi import APIRouter, Request, BackgroundTasks
from fastapi.responses import JSONResponse

# -------------------------------
# UTM 付与（line_utils が無い環境でも動くフォールバック付）
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
    return urlunparse((u.scheme, u.netloc, u.path, u.params, urlencode(q), u.fragment))

try:
    from api.routers.line_utils import with_utm  # type: ignore
except Exception:
    with_utm = _with_utm_fallback  # type: ignore

# ▼ LIFF 各種リンク（固定）
AI_CONSULT_URL = "https://liff.line.me/LIFF_ID_AI?state=rag_home"
AI_SITE_URL    = "https://liff.line.me/LIFF_ID_SITE?state=rag_home"
BUDGET_URL     = "https://liff.line.me/LIFF_ID_BUDGET?state=rm_ai_loan"

ai_consult_link = with_utm(AI_CONSULT_URL, "ai_consult", ab="A")
ai_site_link    = with_utm(AI_SITE_URL,   "ai_site",    ab="A")
budget_link     = with_utm(BUDGET_URL,    "budget",     ab="A")

logger = logging.getLogger(__name__)

# ======================================================================
# RAG / 資金計画の「遅延ロード」— 起動時は解決しない（コールドスタート短縮）
# ======================================================================
import sys, pathlib, importlib
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
        Configuration,
        ApiClient,
        MessagingApi,
        ReplyMessageRequest,
        PushMessageRequest,
        TextMessage,
        ApiException,
    )
    from linebot.v3.webhooks import MessageEvent, TextMessageContent, PostbackEvent, FollowEvent
    LINE_SDK_AVAILABLE = True
    logger.info("✅ LINE Bot SDK v3 imported")
except Exception as e:
    LINE_SDK_AVAILABLE = False
    logger.error(f"❌ LINE Bot SDK import failed: {e}")

    class WebhookHandler:  # ダミー（ローカルlint用）
        def __init__(self, *args, **kwargs): ...
        def add(self, *args, **kwargs):
            def deco(f): return f
            return deco
        def handle(self, *args, **kwargs): ...

# ======================================================================
# ルーター
# ======================================================================
router = APIRouter(prefix="", tags=["line-ultra-fast"])

# ======================================================================
# 設定
# ======================================================================
LINE_RESPONSE_TIMEOUT = int(os.getenv("LINE_RESPONSE_TIMEOUT", "12"))  # 既定12秒
SESSION_TTL = int(os.getenv("SESSION_TTL_MINUTES", "30")) * 60

# ======================================================================
# 固定テンプレ（ご指定文面を維持）
# ======================================================================
RICHMENU_FIXED_RESPONSES: Dict[str, str] = {
    "follow_greeting": """こんにちは！キノエデザインです。
この度は友だち追加ありがとうございます✨

目的のボタンをタップ👇
🤖AI相談 / 📍来場予約 / 📄資料請求 / 💴資金計画 / 🌐サイト / 💬チャット

AIは24時間、担当者は当日〜翌営業日に返信します。

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
※ご使用の前に、必ず以下の取り扱いをご確認ください。
プライバシーポリシー：【https://preview.studio.site/live/EjOQljz1WJ/privacy-policy 】
利用規約：【https://preview.studio.site/live/EjOQljz1WJ/termsofuse/service 】
Cookie：【https://preview.studio.site/live/EjOQljz1WJ/cookie 】""",

    "AI住まいサイト": """🌐 AI住まいサイトのご案内
キノエデザインの住まい情報サイトをご紹介します。（家づくりの疑問にAIが24時間即回答）
🏠 サイト内容：
・AIチャット相談（資金計画／補助金／間取り など）
・施工写真（実例）
・間取りの考え方・プラン例
・よくある質問（最初に迷う3つのこと ほか）
・保存版デジタル冊子 ZINE（無料ダウンロード）
・LINEで無料相談／来場予約
📱 サイトURL：
https://preview.studio.site/live/EjOQljz1WJ/""",

    "資料請求": """📋ありがとうございます！こちらからご覧いただけます。
〔資料タイトル〕（PDF）：〔URL〕
よろしければ簡単アンケート（任意）：
・ご計画時期：今すぐ / 3–6か月 / 1年以内 / 未定
・連絡方法（任意）：このLINE / メール / 連絡不要
※必ず以下の取り扱いをご確認ください。
プライバシーポリシー：【https://preview.studio.site/live/EjOQljz1WJ/privacy-policy 】
利用規約：【https://preview.studio.site/live/EjOQljz1WJ/termsofuse/service 】
Cookie：【https://preview.studio.site/live/EjOQljz1WJ/cookie 】""",

    "展示場来場予約": """📍 展示場のご来場予約につきましては、下記URLより必要事項のご入力をお願い申し上げます。
【https://preview.studio.site/live/EjOQljz1WJ/reservation 】
スタッフ一同、心よりお待ちしております！""",

    "資金計画": """💬 AI資金診断のご案内
本診断は匿名でご利用いただけます。ご回答内容は保存いたしません。算出される金額は試算（概算）であり、目安としてご確認ください。
お手数ですが、以下の5点をご入力ください。
・年収（概算可）
・毎月のご希望返済額
・住宅ローンのご希望借入期間
・ご家族構成（例：大人2名・お子さま1名）
・その他の大きなご負担（例：自動車ローン 等）
未入力の項目があっても進められます。ご入力後、概算結果をご提示いたします。""",

    "チャット相談": """💬 スタッフとのご相談
【対応時間】
営業時間：9:00-18:00
📱 ご相談方法：
・このLINEでの直接相談
・お電話での相談
・展示場での対面相談
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
}

# ======================================================================
# 軽量重複防止（連打/再送対策）
# ======================================================================
class DuplicateGuard:
    def __init__(self):
        self.recent_events: Dict[str, float] = {}
        self.window = 6.0  # 秒

    def seen(self, user_id: str, token: str) -> bool:
        now = time.time()
        key = f"{user_id}:{hashlib.md5(token.encode()).hexdigest()[:8]}"
        t = self.recent_events.get(key)
        self.recent_events[key] = now
        # GC
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
        if not d: return ""
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
    # Secret Manager 併用（任意）
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

LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET = _get_line_tokens()

try:
    configuration_cached: Optional["Configuration"] = None
    api_client_cached: Optional["ApiClient"] = None
    messaging_api_cached: Optional["MessagingApi"] = None
except Exception:
    configuration_cached = api_client_cached = messaging_api_cached = None  # type: ignore

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
    except Exception as e:
        logger.error(f"MessagingApi init failed: {e}")
        return None

if LINE_SDK_AVAILABLE and LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET:
    try:
        handler = WebhookHandler(LINE_CHANNEL_SECRET)
        _ensure_api()
        logger.info("✅ LINE handler initialized")
    except Exception as e:
        logger.error(f"LINE handler init error: {e}")
        handler = None

# ======================================================================
# 送信ヘルパー
# ======================================================================
def _reply_or_push(reply_token: str, user_id: str, text: str) -> bool:
    """まず reply、だめなら push。"""
    api = _ensure_api()
    if not api:
        logger.error("MessagingApi not ready")
        return False

    # 重複防止（同一ユーザーに同一テキストを瞬時多重送信しない）
    if dup_guard.seen(user_id, f"out:{text[:64]}"):
        return True

    try:
        try:
            api.reply_message_with_http_info(
                ReplyMessageRequest(reply_token=reply_token, messages=[TextMessage(text=text)])
            )
            return True
        except ApiException as e:
            if "Invalid reply token" in str(e) or getattr(e, "status", None) == 400:
                api.push_message_with_http_info(
                    PushMessageRequest(to=user_id, messages=[TextMessage(text=text)])
                )
                return True
            logger.error(f"LINE reply failed: {e}")
            return False
    except Exception as e:
        logger.error(f"LINE send failed: {e}")
        return False

def _push(user_id: str, text: str) -> bool:
    """push 専用（最終結果はこちら）"""
    api = _ensure_api()
    if not api:
        logger.error("MessagingApi not ready")
        return False
    if dup_guard.seen(user_id, f"out:{text[:64]}"):
        return True
    try:
        api.push_message_with_http_info(
            PushMessageRequest(to=user_id, messages=[TextMessage(text=text)])
        )
        return True
    except Exception as e:
        logger.error(f"LINE push failed: {e}")
        return False

# ======================================================================
# バックグラウンド・ワーカー
# ======================================================================
def _worker_finance(user_id: str, user_text: str):
    """資金計画：重い計算は別スレッドで実行し、最終結果は push"""
    try:
        run_financial_plan = _resolve_financial_if_needed()
        if run_financial_plan is None:
            _push(user_id, "資金診断を準備中です。時間をおいてお試しください。")
            return
        try:
            import inspect, asyncio
            if inspect.iscoroutinefunction(run_financial_plan):
                result = asyncio.run(run_financial_plan(user_text))
            else:
                result = run_financial_plan(user_text)
        except Exception as e:
            logger.error(f"financial_plan error: {e}")
            result = "うまく処理できませんでした。必要項目（年収・毎月返済額・借入期間・家族構成・その他負担）をもう一度教えてください。"
        _push(user_id, _strip_citations(result or "").strip() or "結果を作成できませんでした。")
    except Exception as e:
        logger.error(f"_worker_finance fatal: {e}")

def _worker_ai(user_id: str, user_text: str):
    """AI相談：RAG で回答し、最終結果は push"""
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
        _push(user_id, _strip_citations(answer or "").strip() or "回答を作成できませんでした。")
    except Exception as e:
        logger.error(f"_worker_ai fatal: {e}")

# ======================================================================
# Webhook（即ACK）
# ======================================================================
@router.post("/line/webhook")
async def line_webhook(request: Request, background_tasks: BackgroundTasks):
    if not handler:
        return JSONResponse({"status": "error", "message": "LINE not configured"}, status_code=500)
    try:
        body = await request.body()
        signature = request.headers.get("X-Line-Signature", "")
        if not signature:
            return JSONResponse({"status": "error", "message": "Missing signature"}, status_code=400)

        # 即ACK（処理はバックグラウンド）
        background_tasks.add_task(handler.handle, body.decode("utf-8"), signature)
        return JSONResponse({"status": "ok", "ts": datetime.now().isoformat()})
    except Exception as e:
        logger.error(f"webhook error: {e}")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

# ======================================================================
# イベントハンドラ（reply→push 方針）
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

            # 連打/再送ガード
            if dup_guard.seen(user_id, f"in:{text[:64]}"):
                return

            # リッチメニュー押下→テンプレ即返 & モード開始
            key = None
            if text in RICHMENU_FIXED_RESPONSES:
                key = text
            else:
                for k, mapped in RICHMENU_KEYWORD_MAPPING.items():
                    if k in text:
                        key = mapped
                        break

            if key:
                if key == "AI相談":
                    sessions.set_mode(user_id, "ai")
                elif key == "資金計画":
                    sessions.set_mode(user_id, "finance")
                _reply_or_push(reply_token, user_id, RICHMENU_FIXED_RESPONSES[key])
                return

            mode = sessions.get_mode(user_id)

            # 資金計画モード：即時ACK → BGで計算 → push最終
            if mode == "finance":
                _reply_or_push(reply_token, user_id, "📊 試算中です。少しお待ちください…")
                threading.Thread(target=_worker_finance, args=(user_id, text), daemon=True).start()
                return

            # AI相談モード：即時ACK → BGでRAG → push最終
            if mode == "ai":
                _reply_or_push(reply_token, user_id, "🔎 少しお待ちください…")
                threading.Thread(target=_worker_ai, args=(user_id, text), daemon=True).start()
                return

            # 既定（案内）
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

            if dup_guard.seen(user_id, f"post:{data[:64]}"):
                return

            key = None
            if data in RICHMENU_FIXED_RESPONSES:
                key = data
            elif "action=" in data:
                for part in data.split("&"):
                    if part.startswith("action="):
                        act = part.split("=", 1)[1]
                        if act in RICHMENU_KEYWORD_MAPPING:
                            key = RICHMENU_KEYWORD_MAPPING[act]
                        elif act in RICHMENU_FIXED_RESPONSES:
                            key = act
                        break

            if key:
                if key == "AI相談":
                    sessions.set_mode(user_id, "ai")
                elif key == "資金計画":
                    sessions.set_mode(user_id, "finance")
                _reply_or_push(reply_token, user_id, RICHMENU_FIXED_RESPONSES[key])
                return

            _reply_or_push(
                reply_token,
                user_id,
                "目的のボタンをタップしてください😊\n\n:robot:AI相談 / :round_pushpin:来場予約 / :page_facing_up:資料請求 / :yen:資金計画 / :globe_with_meridians:サイト / :speech_balloon:チャット",
            )
        except Exception as e:
            logger.error(f"postback handler error: {e}")

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
