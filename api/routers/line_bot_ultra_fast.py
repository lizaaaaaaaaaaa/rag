import logging
import os
import re
import asyncio
import time
import hashlib
from datetime import datetime
from typing import Dict, Optional, Any, Tuple

from fastapi import APIRouter, Request, BackgroundTasks
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# ==============================================================================
# RAG 応答（robust import; どの配置でも拾う）— services/rag_chain を最優先
# ==============================================================================
import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[2]  # .../RAG-LLM-Project
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

get_rag_response = None
for cand in ("services.rag_chain", "rag.rag_chain", "rag_chain"):
    try:
        mod = __import__(cand, fromlist=["get_rag_response"])
        get_rag_response = getattr(mod, "get_rag_response")
        logger.info(f"RAG module resolved via: {cand}")
        break
    except Exception:
        continue

# 資金計画 LLM 呼び出し（存在すれば利用）
run_financial_plan = None
for cand in ("financial_api", "services.financial_api"):
    try:
        mod = __import__(cand, fromlist=["run_financial_plan"])
        run_financial_plan = getattr(mod, "run_financial_plan")
        logger.info(f"Financial API resolved via: {cand}")
        break
    except Exception:
        continue

# ==============================================================================
# 出典/参考/資料の文言は一切表示しない
# ==============================================================================
def _strip_citations(text: str) -> str:
    if not text:
        return text
    text = re.sub(r"^\s*(参考|資料|出典)\s*[:：].*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"【出典】[\s\S]*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s*\(p\.\s*\d+\s*\)\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text

# ==============================================================================
# LINE SDK v3
# ==============================================================================
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

# ==============================================================================
# ルーター
# ==============================================================================
router = APIRouter(prefix="", tags=["line-ultra-fast"])

# ==============================================================================
# 固定テンプレ（必要に応じ編集OK）
# ==============================================================================
RICHMENU_FIXED_RESPONSES = {
    "follow_greeting": """こんにちは！キノエデザインです。
この度は友だち追加ありがとうございます✨

目的のボタンをタップ👇
🤖AI相談 / 📍来場予約 / 📄資料請求 / 💰資金計画 / 🌐サイト / 💬チャット

AIは24時間、担当者は当日〜翌営業日に返信します。

※ご使用の前に、必ず以下の取り扱いをご確認ください。
プライバシーポリシー：【https://preview.studio.site/live/EjOQljz1WJ/privacy-policy 】
利用規約：【https://preview.studio.site/live/EjOQljz1WJ/termsofuse/service 】
Cookie：【https://preview.studio.site/live/EjOQljz1WJ/cookie 】""",
    "🤖 AI相談": """🤖 AI住まい相談を開始します！

住まいに関するご質問をお気軽にどうぞ。

💡 例）
・坪単価はどのくらい？
・標準仕様は？
・耐震/断熱性能は？

※ご使用の前に、必ず以下の取り扱いをご確認ください。
プライバシーポリシー：【https://preview.studio.site/live/EjOQljz1WJ/privacy-policy 】
利用規約：【https://preview.studio.site/live/EjOQljz1WJ/termsofuse/service 】
Cookie：【https://preview.studio.site/live/EjOQljz1WJ/cookie 】""",
    "💰 資金計画": """💬 AI資金診断のご案内

以下の5点をお送りください（概算可）：
・年収
・毎月の希望返済額
・希望借入期間
・家族構成
・その他の大きな負担（例：自動車ローン）

ご入力後、目安レンジと注意点を簡潔にお返しします。""",
}

RICHMENU_KEYWORD_MAPPING = {
    "AI相談": "🤖 AI相談",
    "資金計画": "💰 資金計画",
    # 必要に応じて他ボタンもマップ追加
}

# ==============================================================================
# 軽量重複防止（連打/再送対策）
# ==============================================================================
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

# ==============================================================================
# セッション管理（AI相談 / 資金計画）
# ==============================================================================
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

SESSION_TTL = int(os.getenv("SESSION_TTL_MINUTES", "30")) * 60
sessions = SessionStore(SESSION_TTL)

# ==============================================================================
# LINE クライアント（キャッシュ再利用）
# ==============================================================================
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

configuration_cached: Optional["Configuration"] = None
api_client_cached: Optional["ApiClient"] = None
messaging_api_cached: Optional["MessagingApi"] = None
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

# ==============================================================================
# 送信（reply→push フォールバック）
# ==============================================================================
def _send_message(reply_token: str, user_id: str, text: str) -> bool:
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

# ==============================================================================
# Webhook（即ACK）
# ==============================================================================
@router.post("/line/webhook")
async def line_webhook(request: Request, background_tasks: BackgroundTasks):
    if not handler:
        return JSONResponse({"status": "error", "message": "LINE not configured"}, status_code=500)
    try:
        body = await request.body()
        signature = request.headers.get("X-Line-Signature", "")
        if not signature:
            return JSONResponse({"status": "error", "message": "Missing signature"}, status_code=400)

        body_text = body.decode("utf-8")
        # 即ACK（処理はバックグラウンド）
        background_tasks.add_task(handler.handle, body_text, signature)
        return JSONResponse({"status": "ok", "ts": datetime.now().isoformat()})
    except Exception as e:
        logger.error(f"webhook error: {e}")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

# ==============================================================================
# イベントハンドラ
# ==============================================================================
if LINE_SDK_AVAILABLE and handler:
    @handler.add(FollowEvent)
    def on_follow(event):
        try:
            user_id = event.source.user_id
            if dup_guard.seen(user_id, f"follow:{user_id}"):
                return
            greeting = RICHMENU_FIXED_RESPONSES["follow_greeting"]
            _send_message(event.reply_token, user_id, greeting)
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
                if key == "🤖 AI相談":
                    sessions.set_mode(user_id, "ai")
                elif key == "💰 資金計画":
                    sessions.set_mode(user_id, "finance")
                _send_message(reply_token, user_id, RICHMENU_FIXED_RESPONSES[key])
                return

            mode = sessions.get_mode(user_id)

            # 資金計画モード：ユーザー入力→LLM回答
            if mode == "finance":
                if run_financial_plan is None:
                    _send_message(reply_token, user_id, "資金診断を準備中です。少し時間をおいてお試しください。")
                    return
                try:
                    # 既存の financial_api 側が async なら await へ変更
                    resp = asyncio.run(run_financial_plan(text)) if asyncio.iscoroutinefunction(run_financial_plan) else run_financial_plan(text)
                except Exception as e:
                    logger.error(f"financial_plan error: {e}")
                    resp = "うまく処理できませんでした。もう一度お試しください。"
                _send_message(reply_token, user_id, _strip_citations(resp or ""))
                return

            # AI相談モード：RAGで回答（出典は全面カット）
            if mode == "ai":
                if get_rag_response is None:
                    _send_message(reply_token, user_id, "AI相談の準備中です。少し時間をおいてお試しください。")
                    return
                try:
                    answer, _ = get_rag_response(text)
                except Exception as e:
                    logger.error(f"RAG error: {e}")
                    answer = "該当情報が見つかりませんでした。別の聞き方でお試しください。"
                _send_message(reply_token, user_id, _strip_citations(answer or ""))
                return

            # 既定（案内）
            fallback = (
                "ご質問ありがとうございます😊\n\n"
                "目的のボタンをタップしてください👇\n"
                "🤖AI相談 / 📍来場予約 / 📄資料請求 / 💰資金計画 / 🌐サイト / 💬チャット\n\n"
                "具体的なご質問もお気軽にどうぞ✨"
            )
            _send_message(reply_token, user_id, fallback)
        except Exception as e:
            logger.error(f"message handler error: {e}")
            try:
                _send_message(event.reply_token, event.source.user_id, "一時的にエラーが発生しました。時間をおいてお試しください。")
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

            # データに action=... が来る場合を吸収
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
                if key == "🤖 AI相談":
                    sessions.set_mode(user_id, "ai")
                elif key == "💰 資金計画":
                    sessions.set_mode(user_id, "finance")
                _send_message(reply_token, user_id, RICHMENU_FIXED_RESPONSES[key])
                return

            _send_message(
                reply_token,
                user_id,
                "目的のボタンをタップしてください😊\n\n🤖AI相談 / 📍来場予約 / 📄資料請求 / 💰資金計画 / 🌐サイト / 💬チャット",
            )
        except Exception as e:
            logger.error(f"postback handler error: {e}")

# ==============================================================================
# 簡易ステータス
# ==============================================================================
@router.get("/line/health")
def health():
    return {
        "status": "ok" if (LINE_SDK_AVAILABLE and handler and _ensure_api()) else "degraded",
        "ts": datetime.now().isoformat(),
    }
