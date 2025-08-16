# api/routers/line_bot.py - 即座応答版（リッチメニューは0.1秒以内で応答）

import logging
from pathlib import Path
from datetime import datetime
from uuid import uuid4
import traceback
import os
import re
import json
import asyncio
from typing import Dict, Optional, Any
import concurrent.futures

from fastapi import APIRouter, Request, BackgroundTasks
from fastapi.responses import JSONResponse

# ---- 監視（Cloud Logging） ---------------------------------------------------
from google.cloud import logging as cloud_logging

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
# 即座応答用の事前定義メッセージ（静的コンテンツ）
# ==============================================================================

# リッチメニュー用の即座応答メッセージ（事前定義・計算不要）
INSTANT_RICHMENU_RESPONSES = {
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

    "ai_site": """🌐 AI住まいサイト

キノエデザインの住まい情報サイトです。
住まいづくりに関する豊富な情報をご提供しています。

📍 https://kinoe-design.com

詳しい情報はサイトをご確認ください🏠""",

    "document_request": """📋 資料請求を承ります

以下の情報をお送りください：
1️⃣ お名前（フルネーム）
2️⃣ ご住所（〒郵便番号から）
3️⃣ お電話番号
4️⃣ ご希望資料

📮 3営業日以内にお送りいたします""",

    "exhibition_reservation": """📍 展示場来場予約

以下をメッセージでお送りください：
・ご希望日時（第1・第2希望）
・お名前
・お電話番号
・参加人数

🏠 スタッフ一同、お待ちしております""",

    "finance_planning": """💰 資金計画・住宅ローン相談

住宅ローンや資金計画をサポートします。

お聞かせください：
・ご年収
・自己資金
・ご希望借入額
・返済期間

最適なプランをご提案いたします💡""",

    "chat_consultation": """💬 スタッフとのご相談

【対応時間】9:00-18:00（水曜定休）

住まいづくりのご質問をお気軽にどうぞ。
営業時間内でしたら迅速にお返事します📱

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
ご不明な点がございましたら、スタッフまでお問い合わせください。""",

    "follow_welcome": """🎉 友達追加ありがとうございます！

キノエデザインの住まいAIコンシェルジュです。
画面下のメニューから各種サービスをご利用いただけます。

🤖 AI相談 / 📋 資料請求 / 📍 展示場予約 / 💰 資金計画 / 💬 チャット相談"""
}

# ==============================================================================
# 共通ユーティリティ
# ==============================================================================

def normalize_line_token(token: Any) -> str:
    """LINE トークンを安全に string 型へ正規化"""
    if token is None:
        return ""
    if isinstance(token, bytes):
        try:
            token = token.decode("utf-8")
        except UnicodeDecodeError:
            logger.error("Failed to decode token from bytes")
            return ""
    token_str = str(token).strip()
    if token_str.startswith("Bearer "):
        token_str = token_str[7:].strip()
    if token_str.startswith("b'") and token_str.endswith("'"):
        token_str = token_str[2:-1]
    return token_str


def make_json_serializable(obj: Any) -> Any:
    """オブジェクトをJSONシリアライズ可能に変換"""
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
        return f'{{"error":"serialization_failed","type":"{type(obj).__name__}"}}'


# ==============================================================================
# 監視・メトリクス
# ==============================================================================

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
            "instant_responses": 0,  # 即座応答カウンター
            "richmenu_responses": 0,  # リッチメニュー応答カウンター
        }
        try:
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
        """即座応答のカウント"""
        self.stats["instant_responses"] += 1

    def track_richmenu_response(self):
        """リッチメニュー応答のカウント"""
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
        import main
        return {
            "vectorstore": getattr(main, "vectorstore", None),
            "rag_chain_template": getattr(main, "rag_chain_template", None),
            "llm_instance": getattr(main, "llm_instance", None),
        }
    except Exception as e:
        logger.error(f"Failed to get app globals: {e}")
        return {"vectorstore": None, "rag_chain_template": None, "llm_instance": None}

# ==============================================================================
# 送信（安全版）
# ==============================================================================

def send_line_reply_safe(reply_token: str, message_text: str) -> bool:
    """安全な返信送信（都度Configuration生成＋例外ハンドリング）"""
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

# ==============================================================================
# 【即座応答】リッチメニュー処理
# ==============================================================================

def detect_richmenu_action_instant(message_text: str) -> str:
    """即座判定：リッチメニューアクション（計算不要）"""
    text_lower = message_text.lower().replace(" ", "").replace("　", "")
    
    # 最重要パターンを最初に判定（即座判定）
    if "ai相談" in text_lower:
        return "ai_consultation"
    elif "資料請求" in text_lower:
        return "document_request"
    elif "展示場" in text_lower or "見学" in text_lower:
        return "exhibition_reservation"
    elif "資金計画" in text_lower or "ローン" in text_lower:
        return "finance_planning"
    elif "チャット" in text_lower or "スタッフ" in text_lower:
        return "chat_consultation"
    elif "ai住まい" in text_lower or "aiサイト" in text_lower:
        return "ai_site"
    elif any(g in text_lower for g in ["こんにちは", "はじめまして", "よろしく"]):
        return "greeting"
    return "general"

def get_instant_richmenu_response(action: str) -> str:
    """即座応答：事前定義メッセージを返すだけ（計算ゼロ）"""
    monitor.track_instant_response()
    monitor.track_richmenu_response()
    
    # 事前定義された静的メッセージを即座に返す
    return INSTANT_RICHMENU_RESPONSES.get(action, INSTANT_RICHMENU_RESPONSES["unknown"])

# ==============================================================================
# 【通常のRAG処理】メッセージイベント用（質問応答のみ）
# ==============================================================================

# 通常のRAG応答キャッシュ（質問応答用）
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
    """ユーザーの質問に対するRAG/LLM処理（リッチメニュー以外）"""
    try:
        # キャッシュ確認
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

        # 簡単な挨拶の即座応答
        simple_greetings = {
            "こんにちは": "こんにちは！住まいづくりのご質問をお気軽にどうぞ🏠",
            "ありがとう": "どういたしまして！他にもご質問がございましたらお聞かせください🙏",
            "おはよう": "おはようございます！今日も住まいづくりのお手伝いをいたします☀️",
        }
        for greeting, response in simple_greetings.items():
            if greeting in message_text:
                cache_message_response(message_text, response)
                return response

        # RAG処理（5秒タイムアウト）
        if vectorstore and rag_chain_template:
            logger.info("📚 Processing user question with RAG...")
            
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
                    # 基本的なクリーンアップ
                    answer = re.sub(r'[^\s]*しましょう[。！？]*', '', answer)
                    answer = answer.strip()
                    
                    if len(answer) > 300:
                        answer = answer[:280] + "詳細はお問い合わせください。"
                    
                    cache_message_response(message_text, answer)
                    logger.info(f"✅ RAG answer generated: {len(answer)} chars")
                    return answer
                else:
                    raise ValueError("Empty or insufficient RAG response")
                    
            except asyncio.TimeoutError:
                logger.warning("⏰ RAG timeout for user question")
                fallback = get_emergency_response_for_question(message_text)
                cache_message_response(message_text, fallback)
                return fallback
            except Exception as e:
                logger.error(f"❌ RAG error for user question: {e}")
                fallback = get_emergency_response_for_question(message_text)
                cache_message_response(message_text, fallback)
                return fallback

        # LLMのみの場合
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
                fallback = get_emergency_response_for_question(message_text)
                cache_message_response(message_text, fallback)
                return fallback

        fallback = get_emergency_response_for_question(message_text)
        cache_message_response(message_text, fallback)
        return fallback

    except Exception as e:
        logger.error(f"💥 User question processing error: {e}")
        fallback = "申し訳ございません。エラーが発生しました。再度お試しください。"
        cache_message_response(message_text, fallback)
        return fallback

def get_emergency_response_for_question(message_text: str) -> str:
    """質問に対する緊急応答"""
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
# イベントハンドラ（即座応答版）
# ==============================================================================

if LINE_SDK_AVAILABLE and handler:

    @handler.add(MessageEvent, message=TextMessageContent)
    def handle_text_message(event):
        """メッセージイベント：リッチメニューは即座、質問は通常処理"""
        start = datetime.now()
        try:
            user_id = event.source.user_id
            message_text = event.message.text
            logger.info(f"📱 Message from {user_id}: '{message_text[:100]}...'")

            # 1. リッチメニューメッセージかチェック（即座判定）
            action = detect_richmenu_action_instant(message_text)
            
            if action != "general":
                # リッチメニューメッセージ → 即座応答（計算ゼロ）
                logger.info(f"⚡ Instant richmenu response for action: {action}")
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
                })
                logger.info(f"✅ Instant richmenu reply sent={send_ok} time={dur:.3f}s action={action}")
                return

            # 2. 通常の質問 → RAG/LLM処理（非同期）
            logger.info("🔄 Processing user question with RAG/LLM...")
            
            def _process_question():
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    answer = loop.run_until_complete(process_user_question(message_text, user_id))
                    loop.close()
                    return answer
                except Exception as e:
                    logger.error(f"Question processing error: {e}")
                    return get_emergency_response_for_question(message_text)

            # 5秒タイムアウトで質問処理
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
        """Postbackイベント：完全即座応答（計算一切なし）"""
        start = datetime.now()
        try:
            user_id = event.source.user_id
            postback_data = event.postback.data or ""
            logger.info(f"🔙 Instant postback from {user_id}: {postback_data}")

            # data=action=xxx&source=... の解析（最小限）
            action = "unknown"
            try:
                if "action=" in postback_data:
                    for part in postback_data.split("&"):
                        if part.startswith("action="):
                            action = part.split("=", 1)[1]
                            break
            except Exception as e:
                logger.error(f"Postback parse error: {e}")

            # 事前定義メッセージを即座に返す（計算ゼロ）
            response_text = get_instant_richmenu_response(action)

            send_ok = send_line_reply_safe(event.reply_token, response_text)
            dur = (datetime.now() - start).total_seconds()
            
            monitor.log_webhook_event("postback", send_ok, {
                "user_id": user_id, 
                "action": action, 
                "processing_time": dur,
                "response_type": "instant_postback"
            })
            logger.info(f"✅ Instant postback reply sent={send_ok} time={dur:.3f}s action={action}")
            
        except Exception as e:
            dur = (datetime.now() - start).total_seconds()
            logger.error(f"💥 Postback handler error: {e}")
            monitor.log_webhook_event("postback", False, {"error": str(e), "processing_time": dur})

    @handler.add(FollowEvent)
    def handle_follow(event):
        """フォローイベント：即座応答"""
        try:
            user_id = event.source.user_id
            welcome = INSTANT_RICHMENU_RESPONSES["follow_welcome"]
            send_ok = send_line_reply_safe(event.reply_token, welcome)
            monitor.log_webhook_event("follow", send_ok, {"user_id": user_id, "response_type": "instant_follow"})
            monitor.track_instant_response()
        except Exception as e:
            logger.error(f"❌ Follow handler error: {e}")
            monitor.log_webhook_event("follow", False, {"error": str(e)})

    @handler.add(UnfollowEvent)
    def handle_unfollow(event):
        try:
            user_id = event.source.user_id
            monitor.log_webhook_event("unfollow", True, {"user_id": user_id, "timestamp": datetime.now().isoformat()})
            logger.info(f"👋 User unfollowed: {user_id}")
        except Exception as e:
            logger.error(f"❌ Unfollow handler error: {e}")
            monitor.log_webhook_event("unfollow", False, {"error": str(e)})

# ==============================================================================
# 管理・診断
# ==============================================================================

@router.get("/health")
def get_comprehensive_health():
    return {
        "line_bot_status": {
            "configured": bool(line_bot_api and handler),
            "sdk_available": LINE_SDK_AVAILABLE,
            "credentials_set": bool(LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET),
        },
        "send_statistics": {
            "success_count": monitor.stats["send_success"],
            "failure_count": monitor.stats["send_failures"],
            "success_rate": monitor.get_send_success_rate(),
        },
        "webhook_statistics": {
            "total_received": monitor.stats["webhook_received"],
            "message_events": monitor.stats["message_events"],
            "postback_events": monitor.stats["postback_events"],
            "follow_events": monitor.stats["follow_events"],
            "error_count": monitor.stats["errors"],
            "error_rate": monitor.get_error_rate(),
        },
        "instant_response_metrics": {
            "instant_responses": monitor.stats["instant_responses"],
            "richmenu_responses": monitor.stats["richmenu_responses"],
            "message_cache_size": len(_message_response_cache),
            "static_responses_loaded": len(INSTANT_RICHMENU_RESPONSES),
        },
        "system_info": {
            "timestamp": datetime.now().isoformat(),
            "instant_response_mode": True,
            "richmenu_response_time": "< 0.1 seconds",
            "user_question_timeout": "5 seconds"
        },
    }

@router.get("/status")
def get_detailed_line_status():
    return {
        "line_bot_configured": bool(line_bot_api and handler),
        "line_sdk_available": LINE_SDK_AVAILABLE,
        "token_length": len(LINE_CHANNEL_ACCESS_TOKEN) if LINE_CHANNEL_ACCESS_TOKEN else 0,
        "secret_length": len(LINE_CHANNEL_SECRET) if LINE_CHANNEL_SECRET else 0,
        "send_success_rate": monitor.get_send_success_rate(),
        "instant_response_enabled": True,
        "richmenu_actions_available": list(INSTANT_RICHMENU_RESPONSES.keys()),
        "performance_mode": "instant_richmenu",
        "timestamp": datetime.now().isoformat(),
    }

@router.post("/test")
async def test_line_bot():
    """テスト：即座応答と通常処理の両方をテスト"""
    if not handler:
        return {"status": "error", "message": "LINE Bot not configured"}
    
    try:
        results = {}
        
        # 1. リッチメニューテスト（即座応答）
        richmenu_test = "AI相談"
        start_time = datetime.now()
        action = detect_richmenu_action_instant(richmenu_test)
        richmenu_response = get_instant_richmenu_response(action)
        richmenu_time = (datetime.now() - start_time).total_seconds()
        
        results["richmenu_test"] = {
            "input": richmenu_test,
            "action": action,
            "response": richmenu_response[:100] + "..." if len(richmenu_response) > 100 else richmenu_response,
            "processing_time_seconds": richmenu_time,
            "type": "instant_response"
        }
        
        # 2. 質問テスト（RAG/LLM処理）
        question_test = "坪単価について教えてください"
        start_time = datetime.now()
        question_response = await process_user_question(question_test, "test-user")
        question_time = (datetime.now() - start_time).total_seconds()
        
        results["question_test"] = {
            "input": question_test,
            "response": question_response[:100] + "..." if len(question_response) > 100 else question_response,
            "processing_time_seconds": question_time,
            "type": "rag_llm_processing"
        }
        
        return {
            "status": "success",
            "test_results": results,
            "performance_metrics": {
                "instant_responses": monitor.stats["instant_responses"],
                "richmenu_responses": monitor.stats["richmenu_responses"],
                "message_cache_size": len(_message_response_cache),
                "richmenu_actions": len(INSTANT_RICHMENU_RESPONSES)
            },
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {"status": "error", "error": str(e), "timestamp": datetime.now().isoformat()}