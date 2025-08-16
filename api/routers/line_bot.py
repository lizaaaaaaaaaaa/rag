# api/routers/line_bot.py - 即座応答最適化・完全修正版
# - リッチメニューは 0.1秒以内に応答（計算ゼロ）
# - RAG/LLM は質問時のみ（5秒タイムアウト）
# - main.py からの診断用 API で使用する公開関数をエクスポート

import logging
import os
import re
import json
import asyncio
import traceback
from datetime import datetime
from typing import Dict, Optional, Any
import concurrent.futures

from fastapi import APIRouter, Request, BackgroundTasks
from fastapi.responses import JSONResponse

# ---- 監視（Cloud Logging） ---------------------------------------------------
try:
    from google.cloud import logging as cloud_logging
except Exception:
    cloud_logging = None

# ---- LINE Bot SDK v3 ---------------------------------------------------------
try:
    from linebot.v3 import WebhookHandler
    from linebot.v3.exceptions import InvalidSignatureError
    from linebot.v3.messaging import (
        Configuration,
        ApiClient,
        MessagingApi,
        ReplyMessageRequest,
        TextMessage,
    )
    from linebot.v3.webhooks import (
        MessageEvent,
        TextMessageContent,
        PostbackEvent,
        FollowEvent,
        UnfollowEvent,
    )
    LINE_SDK_AVAILABLE = True
    logger = logging.getLogger(__name__)
    logger.info("✅ LINE Bot SDK v3.x loaded successfully")
except ImportError as e:
    logging.getLogger(__name__).error(f"LINE Bot SDK not available: {e}")
    LINE_SDK_AVAILABLE = False

    class WebhookHandler:  # ダミー（ローカル開発用）
        def __init__(self, *args, **kwargs): ...
        def add(self, *args, **kwargs):
            def decorator(func): return func
            return decorator
        def handle(self, *args, **kwargs): ...

logger = logging.getLogger(__name__)

# ==============================================================================
# 監視・メトリクス
# ==============================================================================
def make_json_serializable(obj: Any) -> Any:
    try:
        if obj is None:
            return None
        if isinstance(obj, (str, int, float, bool)):
            return obj
        if isinstance(obj, (list, tuple)):
            return [make_json_serializable(x) for x in obj]
        if isinstance(obj, dict):
            return {str(k): make_json_serializable(v) for k, v in obj.items()}
        if isinstance(obj, set):
            return list(obj)
        if hasattr(obj, "__dict__"):
            return make_json_serializable(obj.__dict__)
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        return str(obj)
    except Exception as e:
        logger.warning(f"Failed to serialize object {type(obj)}: {e}")
        return str(obj)

def safe_json_dumps(obj: Any, **kwargs) -> str:
    try:
        return json.dumps(make_json_serializable(obj), ensure_ascii=False, **kwargs)
    except Exception as e:
        logger.error(f"JSON serialization failed: {e}")
        return '{"error":"serialization_failed"}'

class ComprehensiveMonitor:
    def __init__(self):
        self.stats = {
            "webhook_received": 0,
            "postback_events": 0,
            "message_events": 0,
            "follow_events": 0,
            "unfollow_events": 0,
            "errors": 0,
            "send_success": 0,
            "send_failures": 0,
            "response_times": [],
            "last_activity": None,
            "instant_responses": 0,
            "richmenu_responses": 0,
        }
        try:
            if cloud_logging:
                cloud_logging.Client().setup_logging()
                logger.info("✅ Cloud Logging setup completed")
        except Exception as e:
            logger.warning(f"Cloud Logging setup failed: {e}")

    def log_webhook_event(self, event_type: str, success: bool = True, event_data: dict = None):
        self.stats["webhook_received"] += 1
        self.stats["last_activity"] = datetime.now()
        if event_type == "postback":
            self.stats["postback_events"] += 1
        elif event_type == "message":
            self.stats["message_events"] += 1
        elif event_type == "follow":
            self.stats["follow_events"] += 1
        elif event_type == "unfollow":
            self.stats["unfollow_events"] += 1
        if not success:
            self.stats["errors"] += 1

        data = {
            "event_type": event_type,
            "success": success,
            "timestamp": self.stats["last_activity"].isoformat(),
            "error_rate": self.get_error_rate(),
        }
        if event_data:
            data["event_data"] = make_json_serializable(event_data)

        msg = safe_json_dumps(data)
        (logger.info if success else logger.error)(f"LINE Event: {msg}")

    def track_send_result(self, success: bool, error_msg: str = None):
        if success:
            self.stats["send_success"] += 1
        else:
            self.stats["send_failures"] += 1
            if error_msg:
                logger.error(f"Send failure: {error_msg}")

    def track_instant_response(self):
        self.stats["instant_responses"] += 1

    def track_richmenu_response(self):
        self.stats["richmenu_responses"] += 1

    def get_error_rate(self) -> float:
        total = max(self.stats["webhook_received"], 1)
        return self.stats["errors"] / total

    def get_send_success_rate(self) -> float:
        total = self.stats["send_success"] + self.stats["send_failures"]
        return 1.0 if total == 0 else self.stats["send_success"] / total

monitor = ComprehensiveMonitor()

# ==============================================================================
# LINE Bot 初期化（トークン正規化＆検証）
# ==============================================================================
def normalize_line_token(token: Any) -> str:
    if token is None:
        return ""
    if isinstance(token, bytes):
        try:
            token = token.decode("utf-8")
        except UnicodeDecodeError:
            logger.error("Failed to decode token from bytes")
            return ""
    s = str(token).strip()
    if s.startswith("Bearer "):
        s = s[7:].strip()
    if s.startswith("b'") and s.endswith("'"):
        s = s[2:-1]
    return s

def get_normalized_line_credentials():
    raw_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    raw_secret = os.getenv("LINE_CHANNEL_SECRET")
    access_token = normalize_line_token(raw_token)
    channel_secret = normalize_line_token(raw_secret)
    logger.info(f"Token normalization - Raw type: {type(raw_token)}, Normalized length: {len(access_token)}")
    logger.info(f"Secret normalization - Raw type: {type(raw_secret)}, Normalized length: {len(channel_secret)}")
    return access_token, channel_secret

LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET = get_normalized_line_credentials()

if LINE_SDK_AVAILABLE and LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET:
    try:
        configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
        handler = WebhookHandler(LINE_CHANNEL_SECRET)
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
        logger.info("✅ LINE Bot API v3 initialized successfully")
    except Exception as e:
        logger.error(f"❌ LINE Bot API initialization failed: {e}")
        line_bot_api, handler = None, None
else:
    line_bot_api, handler = None, None
    if LINE_SDK_AVAILABLE:
        logger.warning("⚠️ LINE Bot credentials not found")
    else:
        logger.warning("⚠️ LINE Bot SDK not available")

router = APIRouter(prefix="/line", tags=["line"])

# ==============================================================================
# アプリ共有オブジェクト
# ==============================================================================
def get_app_globals():
    """main モジュールから共有オブジェクト取得"""
    try:
        import main  # 循環注意：関数内 import
        return {
            "vectorstore": getattr(main, "vectorstore", None),
            "rag_chain_template": getattr(main, "rag_chain_template", None),
            "llm_instance": getattr(main, "llm_instance", None),
        }
    except Exception as e:
        logger.error(f"Failed to get app globals: {e}")
        return {"vectorstore": None, "rag_chain_template": None, "llm_instance": None}

# ==============================================================================
# 【即座応答】リッチメニュー処理
# ==============================================================================
def detect_richmenu_action_instant(message_text: str) -> str:
    """即座判定：リッチメニューアクション（完全対応版）"""
    text_lower = message_text.lower().replace(" ", "").replace("　", "")

    # 画像のリッチメニューに完全対応（優先度順）
    if "ai相談" in text_lower or text_lower == "ai相談":
        return "ai_consultation"
    elif "ai住まいサイト" in text_lower or text_lower == "ai住まいサイト" or "aiサイト" in text_lower:
        return "ai_site"
    elif "資料請求" in text_lower or text_lower == "資料請求":
        return "document_request"
    elif "展示場来場予約" in text_lower or text_lower == "展示場来場予約" or "展示場予約" in text_lower or "展示場" in text_lower:
        return "exhibition_reservation"
    elif "資金計画" in text_lower or text_lower == "資金計画" or "ローン" in text_lower:
        return "finance_planning"
    elif "チャット相談" in text_lower or text_lower == "チャット相談" or "チャット" in text_lower:
        return "chat_consultation"
    # 一般的な挨拶
    elif any(g in text_lower for g in ["こんにちは", "はじめまして", "よろしく"]):
        return "greeting"

    return "general"

INSTANT_RICHMENU_RESPONSES: Dict[str, str] = {
    "ai_consultation": """🤖 AI住まい相談を開始します！

キノエデザインの住まいAIコンシェルジュです。
住まいに関するご質問をお気軽にどうぞ！

💡 例えば、こんなご質問にお答えします：
・「坪単価について教えて」
・「標準仕様はどんな感じ？」
・「耐震性能について知りたい」
・「断熱性能はどのくらい？」
・「間取りのアドバイスが欲しい」
・「住宅ローンについて相談したい」

何でもお聞きください😊""",

    "ai_site": """🌐 AI住まいサイトのご案内

キノエデザインの住まい情報サイトをご紹介します。

🏠 サイト内容：
・施工事例・間取りプラン
・住宅性能・標準仕様
・価格・坪単価情報
・お客様の声

📱 アクセス方法：
こちらのリンクからご覧ください
https://kinoe-design.com

詳しい住まい情報をご確認いただけます！""",

    "document_request": """📋 資料請求を承ります

以下の情報をお送りください：

📝 必要情報：
1️⃣ お名前（フルネーム）
2️⃣ ご住所（〒郵便番号から）
3️⃣ お電話番号
4️⃣ ご希望資料の種類

📮 お送りする資料：
・会社案内・施工事例集
・間取りプラン集
・価格・仕様資料
・住宅ローンガイド

3営業日以内にお送いたします！""",

    "exhibition_reservation": """📍 展示場来場予約を承ります

以下をメッセージでお送りください：

📅 予約情報：
・ご希望日時（第1・第2希望）
・お名前・お電話番号
・参加人数（大人・お子様）
・ご質問・ご要望

🕒 見学時間：約90分
🏠 展示場：最新の住宅仕様をご確認

スタッフ一同、心よりお待ちしております！
ご質問もお気軽にどうぞ。""",

    "finance_planning": """💰 資金計画・住宅ローン相談

住宅購入の資金計画をサポートします。

📊 ご相談内容：
・住宅ローンの種類・金利比較
・月々の返済計画
・頭金・諸費用の計算
・住宅ローン控除について

💡 お聞かせください：
・ご年収・自己資金
・ご希望借入額・返済期間
・家族構成・将来計画

最適なプランをご提案いたします！
お気軽にご相談ください。""",

    "chat_consultation": """💬 スタッフとのご相談

【対応時間】
平日・土日：9:00-18:00
定休日：水曜日

📱 ご相談方法：
・このLINEでの直接相談
・お電話での相談
・展示場での対面相談

🏠 ご相談内容：
・住まいづくり全般
・土地探し・資金計画
・間取り・デザイン
・住宅性能について

営業時間内でしたら迅速にお返事します。
お気軽にお声かけください！""",

    "greeting": """こんにちは！
キノエデザインのAIコンシェルジュです🏠

画面下のメニューから各種サービスをご利用ください。

🤖 AI相談：住まいのご質問
📋 資料請求：カタログ等
📍 展示場予約：見学予約
💰 資金計画：ローン相談
💬 チャット：スタッフと直接相談

どうぞお気軽にご利用ください！""",

    "unknown": """お気軽にお声かけください。
ご不明な点がございましたら、下記メニューをご利用ください。

🤖 AI相談　📋 資料請求　📍 展示場予約
💰 資金計画　💬 チャット相談

スタッフまでお問い合わせください。""",

    "follow_welcome": """🎉 友達追加ありがとうございます！

キノエデザインの住まいAIコンシェルジュです。
画面下のメニューから各種サービスをご利用いただけます。

🤖 AI相談 / 📋 資料請求 / 📍 展示場予約
💰 資金計画 / 💬 チャット相談

住まいづくりのお手伝いをさせていただきます！"""
}

def get_instant_richmenu_response(action: str) -> str:
    monitor.track_instant_response()
    monitor.track_richmenu_response()
    return INSTANT_RICHMENU_RESPONSES.get(action, INSTANT_RICHMENU_RESPONSES["unknown"])

# ==============================================================================
# 質問応答（RAG/LLM）
# ==============================================================================
_message_response_cache: Dict[str, str] = {}
MAX_MESSAGE_CACHE_SIZE = 50

def cache_message_response(message_text: str, response: str):
    if len(_message_response_cache) >= MAX_MESSAGE_CACHE_SIZE:
        oldest_key = next(iter(_message_response_cache))
        del _message_response_cache[oldest_key]
    _message_response_cache[message_text.lower().strip()] = response

def get_cached_message_response(message_text: str) -> Optional[str]:
    return _message_response_cache.get(message_text.lower().strip())

async def process_user_question(message_text: str, user_id: str) -> str:
    try:
        cached = get_cached_message_response(message_text)
        if cached:
            logger.info("💾 Message cache hit")
            return cached

        globals_dict = get_app_globals()
        vectorstore = globals_dict.get("vectorstore")
        rag_chain_template = globals_dict.get("rag_chain_template")
        llm_instance = globals_dict.get("llm_instance")

        if not vectorstore and not llm_instance:
            fallback = "申し訳ございません。システムが準備中です。しばらくしてから再度お試しください。"
            cache_message_response(message_text, fallback)
            return fallback

        simple_greetings = {
            "こんにちは": "こんにちは！住まいづくりのご質問をお気軽にどうぞ🏠",
            "ありがとう": "どういたしまして！他にもご質問がございましたらお聞かせください🙏",
            "おはよう": "おはようございます！今日も住まいづくりのお手伝いをいたします☀️",
        }
        for k, v in simple_greetings.items():
            if k in message_text:
                cache_message_response(message_text, v)
                return v

        if vectorstore and rag_chain_template:
            logger.info("📚 Processing with RAG...")
            async def run_rag():
                loop = asyncio.get_event_loop()
                def _call():
                    if hasattr(rag_chain_template, "invoke"):
                        return rag_chain_template.invoke({"query": message_text})
                    elif callable(rag_chain_template):
                        return rag_chain_template({"query": message_text})
                    return None
                return await loop.run_in_executor(None, _call)
            try:
                result = await asyncio.wait_for(run_rag(), timeout=5.0)
                answer = result.get("result", "") if result else ""
                if answer and len(answer) > 10:
                    answer = re.sub(r'[^\s]*しましょう[。！？]*', '', answer).strip()
                    if len(answer) > 300:
                        answer = answer[:280] + "詳細はお問い合わせください。"
                    cache_message_response(message_text, answer)
                    logger.info(f"✅ RAG answer generated: {len(answer)} chars")
                    return answer
                else:
                    raise ValueError("Empty or insufficient RAG response")
            except asyncio.TimeoutError:
                logger.warning("⏰ RAG timeout")
                fb = get_emergency_response_for_question(message_text)
                cache_message_response(message_text, fb)
                return fb
            except Exception as e:
                logger.error(f"❌ RAG error: {e}")
                fb = get_emergency_response_for_question(message_text)
                cache_message_response(message_text, fb)
                return fb

        if llm_instance:
            logger.info("🤖 Processing with LLM only...")
            try:
                prompt = (
                    "住宅専門アドバイザーとして簡潔に答えてください。\n\n"
                    f"質問: {message_text}\n\n"
                    "【重要】\n- 150文字以内\n- 「〜しましょう」禁止\n- 実用的に\n\n"
                    "回答:"
                )
                if hasattr(llm_instance, "invoke"):
                    resp = llm_instance.invoke(prompt)
                    result = resp.content if hasattr(resp, "content") else str(resp)
                else:
                    resp = llm_instance(prompt)
                    result = str(resp)
                result = re.sub(r'[^\s]*しましょう[。！？]*', '', result).strip()
                cache_message_response(message_text, result)
                return result
            except Exception as e:
                logger.error(f"❌ LLM error: {e}")
                fb = get_emergency_response_for_question(message_text)
                cache_message_response(message_text, fb)
                return fb

        fb = get_emergency_response_for_question(message_text)
        cache_message_response(message_text, fb)
        return fb

    except Exception as e:
        logger.error(f"💥 User question processing error: {e}")
        fb = "申し訳ございません。エラーが発生しました。再度お試しください。"
        cache_message_response(message_text, fb)
        return fb

def get_emergency_response_for_question(message_text: str) -> str:
    if "坪単価" in message_text:
        return "坪単価は約70〜85万円/坪が目安です。詳細はお問い合わせください。"
    elif "資料" in message_text:
        return "資料をお送りします。お名前、ご住所、お電話番号をお教えください。"
    elif "見学" in message_text or "展示" in message_text:
        return "展示場見学を承ります。ご希望日時をお聞かせください。"
    else:
        return "申し訳ございません。詳しくはお問い合わせください。"

# ==============================================================================
# Webhook（署名検証強化）
# ==============================================================================
@router.post("/webhook")
async def line_webhook(request: Request, background_tasks: BackgroundTasks):
    logger.info("🚀 LINE Webhook endpoint called")
    if not line_bot_api or not handler:
        monitor.log_webhook_event("error", False, {"error": "LINE Bot not configured", "sdk": LINE_SDK_AVAILABLE})
        return {"status": "error", "message": "LINE Bot not configured", "timestamp": datetime.now().isoformat()}
    try:
        body = await request.body()
        signature = request.headers.get("X-Line-Signature", "")
        logger.info(f"📨 Webhook received - Body length: {len(body)}, Signature exists: {'Yes' if signature else 'No'}")

        if not signature:
            monitor.log_webhook_event("signature_error", False, {"error": "missing_signature", "body_length": len(body)})
            return {"status": "error", "message": "Missing signature", "timestamp": datetime.now().isoformat()}

        try:
            body_text = body.decode("utf-8")
            logger.debug(f"Body preview: {body_text[:200]}...")
            handler.handle(body_text, signature)
        except InvalidSignatureError as sig_error:
            monitor.log_webhook_event("signature_error", False, {"error": "invalid_signature", "details": str(sig_error)})
            return {"status": "signature_error", "timestamp": datetime.now().isoformat()}
        except Exception as handle_error:
            monitor.log_webhook_event("handler_error", False, {"error": str(handle_error), "type": type(handle_error).__name__})
            return {"status": "handler_error", "timestamp": datetime.now().isoformat()}

        monitor.log_webhook_event("webhook_success", True, {"body_length": len(body)})
        return {"status": "ok", "timestamp": datetime.now().isoformat()}

    except Exception as e:
        monitor.log_webhook_event("unexpected_error", False, {"error": str(e), "type": type(e).__name__})
        logger.error(traceback.format_exc())
        return {"status": "error_handled", "error": str(e), "timestamp": datetime.now().isoformat()}

# ==============================================================================
# イベントハンドラ（即座応答）
# ==============================================================================
if LINE_SDK_AVAILABLE and handler:

    @handler.add(MessageEvent, message=TextMessageContent)
    def handle_text_message(event):
        """メッセージイベント：リッチメニュー最優先で即座応答"""
        start = datetime.now()
        try:
            user_id = event.source.user_id
            message_text = event.message.text
            logger.info(f"📱 Message from {user_id}: '{message_text}'")

            # 1) リッチメニュー即座判定
            action = detect_richmenu_action_instant(message_text)
            if action != "general":
                logger.info(f"⚡ INSTANT richmenu response for action: {action}")
                answer = get_instant_richmenu_response(action)
                send_ok = send_line_reply_safe(event.reply_token, answer)

                dur = (datetime.now() - start).total_seconds()
                monitor.log_webhook_event("message", send_ok, {
                    "user_id": user_id,
                    "processing_time": dur,
                    "message_len": len(message_text),
                    "response_len": len(answer),
                    "response_type": "instant_richmenu",
                    "action": action,
                    "instant_response": True,
                })
                logger.info(f"✅ INSTANT richmenu reply sent={send_ok} time={dur:.3f}s action={action}")
                return

            # 2) 通常の質問 → RAG/LLM（5秒タイムアウト）
            logger.info("🔄 Processing user question with RAG/LLM...")
            def _process_question():
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    answer_local = loop.run_until_complete(process_user_question(message_text, user_id))
                    loop.close()
                    return answer_local
                except Exception as e:
                    logger.error(f"Question processing error: {e}")
                    return get_emergency_response_for_question(message_text)

            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(_process_question)
                try:
                    answer = future.result(timeout=5)
                except concurrent.futures.TimeoutError:
                    logger.error("❌ Question processing timeout (5s)")
                    answer = "処理に時間がかかっています。もう一度お試しください。"

            send_ok = send_line_reply_safe(event.reply_token, answer)
            dur = (datetime.now() - start).total_seconds()
            monitor.log_webhook_event("message", send_ok, {
                "user_id": user_id,
                "processing_time": dur,
                "message_len": len(message_text),
                "response_len": len(answer),
                "response_type": "user_question",
            })
            logger.info(f"✅ Question reply sent={send_ok} time={dur:.2f}s")

        except Exception as e:
            dur = (datetime.now() - start).total_seconds()
            logger.error(f"❌ Message handler error: {e}")
            logger.error(traceback.format_exc())
            monitor.log_webhook_event("message", False, {
                "error": str(e),
                "type": type(e).__name__,
                "processing_time": dur,
            })
            try:
                emergency = get_emergency_response_for_question(message_text if 'message_text' in locals() else "")
                send_line_reply_safe(event.reply_token, emergency)
                logger.info("🆘 Emergency response sent")
            except Exception as final_error:
                logger.error(f"💥 Final emergency error: {final_error}")

    @handler.add(PostbackEvent)
    def handle_postback(event):
        """Postbackイベント：完全即座応答（全メニュー対応）"""
        start = datetime.now()
        try:
            user_id = event.source.user_id
            postback_data = event.postback.data or ""
            logger.info(f"🔙 INSTANT postback from {user_id}: {postback_data}")

            action = "unknown"
            try:
                if "action=" in postback_data:
                    for part in postback_data.split("&"):
                        if part.startswith("action="):
                            action = part.split("=", 1)[1]
                            break
            except Exception as e:
                logger.error(f"Postback parse error: {e}")

            response_text = get_instant_richmenu_response(action)

            send_ok = send_line_reply_safe(event.reply_token, response_text)
            dur = (datetime.now() - start).total_seconds()

            monitor.log_webhook_event("postback", send_ok, {
                "user_id": user_id,
                "action": action,
                "processing_time": dur,
                "response_type": "instant_postback",
                "instant_response": True,
            })
            logger.info(f"✅ INSTANT postback reply sent={send_ok} time={dur:.3f}s action={action}")

        except Exception as e:
            dur = (datetime.now() - start).total_seconds()
            logger.error(f"💥 Postback handler error: {e}")
            monitor.log_webhook_event("postback", False, {"error": str(e), "processing_time": dur})

# ==============================================================================
# 送信（安全版）
# ==============================================================================
def send_line_reply_safe(reply_token: str, message_text: str) -> bool:
    try:
        safe_token = normalize_line_token(LINE_CHANNEL_ACCESS_TOKEN)
        if not safe_token:
            monitor.track_send_result(False, "No valid access token")
            return False
        configuration = Configuration(access_token=safe_token)
        with ApiClient(configuration) as api_client:
            messaging_api = MessagingApi(api_client)
            messaging_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=reply_token,
                    messages=[TextMessage(text=message_text)]
                )
            )
        monitor.track_send_result(True)
        logger.info(f"✅ Reply sent (len={len(message_text)})")
        return True
    except Exception as e:
        err = f"Failed to send reply: {e}"
        logger.error(f"❌ {err}")
        logger.error(traceback.format_exc())
        monitor.track_send_result(False, err)
        return False
