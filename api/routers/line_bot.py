# api/routers/line_bot.py - 超高速応答版（数十秒以内の応答を実現）

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
            "fast_responses": 0,  # 高速応答カウンター
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

    def track_fast_response(self):
        """高速応答のカウント"""
        self.stats["fast_responses"] += 1

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
# 【超高速応答】キャッシュ＆判定＆処理
# ==============================================================================

# --- 超高速メモリキャッシュ ---
_response_cache: Dict[str, str] = {}
_fast_cache: Dict[str, str] = {}  # 超高速専用キャッシュ
MAX_CACHE_SIZE = 100

def _cache_key(text: str) -> str:
    return text.lower().strip()

def get_cached_response(message_text: str) -> Optional[str]:
    # まず超高速キャッシュを確認
    fast_key = _cache_key(message_text)
    if fast_key in _fast_cache:
        monitor.track_fast_response()
        return _fast_cache[fast_key]
    return _response_cache.get(fast_key)

def cache_response(message_text: str, response: str, is_fast: bool = False):
    key = _cache_key(message_text)
    
    # 超高速キャッシュに保存
    if is_fast:
        if len(_fast_cache) >= MAX_CACHE_SIZE:
            oldest_key = next(iter(_fast_cache))
            del _fast_cache[oldest_key]
        _fast_cache[key] = response
    
    # 通常キャッシュに保存
    if len(_response_cache) >= MAX_CACHE_SIZE:
        try:
            oldest_key = next(iter(_response_cache))
            del _response_cache[oldest_key]
        except StopIteration:
            pass
    _response_cache[key] = response

# --- 超高速アクション判定（最重要パターン先頭） ---
def detect_richmenu_action_ultra_fast(message_text: str) -> str:
    """超高速リッチメニューアクション判定（最適化版）"""
    text_lower = message_text.lower().replace(" ", "").replace("　", "")
    
    # 最も重要なパターンを最初に判定
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

# --- 超高速リッチメニュー応答（新メッセージ対応） ---
def get_richmenu_response_ultra_fast(action: str, user_id: str) -> str:
    """超高速リッチメニュー応答（新しいメッセージ対応）"""
    responses = {
        "ai_consultation": (
            "🤖 AI住まい相談を開始します！\n\n"
            "キノエデザインの住まいAIコンシェルジュです。\n"
            "住まいに関するご質問をお気軽にどうぞ！\n\n"
            "💡 例えば、こんなご質問にお答えします：\n"
            "・「坪単価について教えて」\n"
            "・「標準仕様はどんな感じ？」\n"
            "・「耐震性能について知りたい」\n"
            "・「断熱性能はどのくらい？」\n"
            "・「間取りのアドバイスが欲しい」\n"
            "・「住宅ローンについて相談したい」\n\n"
            "何でもお聞きください😊"
        ),
        "ai_site": (
            "🌐 AI住まいサイト\n\n"
            "キノエデザインの住まい情報サイトです。\n"
            "住まいづくりに関する豊富な情報をご提供しています。\n\n"
            "📍 https://kinoe-design.com\n\n"
            "詳しい情報はサイトをご確認ください🏠"
        ),
        "document_request": (
            "📋 資料請求を承ります\n\n"
            "以下の情報をお送りください：\n"
            "1️⃣ お名前（フルネーム）\n"
            "2️⃣ ご住所（〒郵便番号から）\n"
            "3️⃣ お電話番号\n"
            "4️⃣ ご希望資料\n\n"
            "📮 3営業日以内にお送りいたします"
        ),
        "exhibition_reservation": (
            "📍 展示場来場予約\n\n"
            "以下をメッセージでお送りください：\n"
            "・ご希望日時（第1・第2希望）\n"
            "・お名前\n"
            "・お電話番号\n"
            "・参加人数\n\n"
            "🏠 スタッフ一同、お待ちしております"
        ),
        "finance_planning": (
            "💰 資金計画・住宅ローン相談\n\n"
            "住宅ローンや資金計画をサポートします。\n\n"
            "お聞かせください：\n"
            "・ご年収\n"
            "・自己資金\n"
            "・ご希望借入額\n"
            "・返済期間\n\n"
            "最適なプランをご提案いたします💡"
        ),
        "chat_consultation": (
            "💬 スタッフとのご相談\n\n"
            "【対応時間】9:00-18:00（水曜定休）\n\n"
            "住まいづくりのご質問をお気軽にどうぞ。\n"
            "営業時間内でしたら迅速にお返事します📱\n\n"
            "お気軽にお声かけください！"
        ),
        "greeting": (
            "こんにちは！\nキノエデザインのAIコンシェルジュです🏠\n\n"
            "画面下のメニューから各種サービスをご利用ください。\n\n"
            "🤖 AI相談：住まいのご質問\n"
            "📋 資料請求：カタログ等\n"
            "📍 展示場予約：見学予約\n"
            "💰 資金計画：ローン相談\n"
            "💬 チャット：スタッフと直接相談\n\n"
            "どうぞお気軽にご利用ください！"
        ),
    }
    return responses.get(action, "お気軽にお声かけください。")

# --- 回答クレンジング（〜しましょう系の除去） ---
def clean_answer_ultra_fast(answer: str) -> str:
    """超高速回答クレンジング"""
    if not answer:
        return ""
    # 〜しましょう系（表記揺れ含む）を除去
    answer = re.sub(r"[^\s]*しましょう[。！？]*", "", answer)
    answer = re.sub(r"一緒に[^\s]*しましょう[。！？]*", "", answer)
    answer = re.sub(r"〜しましょう[。！？]*", "", answer)
    answer = answer.strip()
    if answer and not answer.endswith(("。", "！", "？")):
        if answer.endswith(("です", "ます")):
            answer += "。"
        elif answer.endswith("、"):
            answer = answer[:-1] + "。"
        else:
            answer += "。"
    return answer

# --- 緊急応答（超高速） ---
def get_emergency_response_ultra_fast(message_text: str) -> str:
    """超高速緊急応答"""
    if "坪単価" in message_text:
        return "坪単価は約70〜85万円/坪が目安です。詳細はお問い合わせください。"
    elif "資料" in message_text:
        return "資料をお送りします。お名前、ご住所、お電話番号をお教えください。"
    elif "見学" in message_text or "展示" in message_text:
        return "展示場見学を承ります。ご希望日時をお聞かせください。"
    else:
        return "申し訳ございません。詳しくはお問い合わせください。"

# --- 超高速RAG ---
async def process_rag_query_ultra_fast(message_text: str, user_id: str) -> str:
    """LINE向け超高速RAG（5秒タイムアウト＆短文化）"""
    try:
        globals_dict = get_app_globals()
        vectorstore = globals_dict.get("vectorstore")
        rag_chain_template = globals_dict.get("rag_chain_template")
        llm_instance = globals_dict.get("llm_instance")

        if not vectorstore and not llm_instance:
            logger.warning("⚠️ No RAG components available - ultra fast fallback")
            return get_emergency_response_ultra_fast(message_text)

        # 挨拶即時応答（超軽量）
        quick_responses = {
            "こんにちは": "こんにちは！住まいづくりのご質問をお気軽にどうぞ🏠",
            "ありがとう": "どういたしまして！他にもご質問がございましたらお聞かせください🙏",
            "おはよう": "おはようございます！今日も住まいづくりのお手伝いをいたします☀️",
        }
        for k, v in quick_responses.items():
            if k in message_text:
                cache_response(message_text, v, is_fast=True)
                return v

        # RAG（5秒タイムアウト）- 大幅短縮
        if vectorstore and rag_chain_template:
            logger.info("📚 Ultra fast RAG processing...")
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
                result = await asyncio.wait_for(run_rag(), timeout=5.0)  # 8秒→5秒に短縮
                answer = result.get("result", "") if result else ""
                if answer and len(answer) > 10:
                    answer = clean_answer_ultra_fast(answer)
                    if len(answer) > 200:  # 300→200に短縮
                        answer = answer[:180] + "詳細はお問い合わせください。"
                    cache_response(message_text, answer, is_fast=True)
                    logger.info(f"✅ Ultra fast RAG success: {len(answer)} chars")
                    return answer
                else:
                    raise ValueError("Empty or insufficient RAG response")
            except asyncio.TimeoutError:
                logger.warning("⏰ Ultra fast RAG timeout - switching to emergency fallback")
                return get_emergency_response_ultra_fast(message_text)
            except Exception as e:
                logger.error(f"❌ Ultra fast RAG error: {e}")
                return get_emergency_response_ultra_fast(message_text)

        # LLMのみ（80文字以内）- さらに短縮
        if llm_instance:
            logger.info("🤖 Ultra fast LLM processing...")
            try:
                quick_prompt = (
                    "住宅専門アドバイザーとして簡潔に答えてください。\n\n"
                    f"質問: {message_text}\n\n"
                    "【重要】\n- 80文字以内\n- 「〜しましょう」禁止\n- 実用的に\n\n"
                    "回答:"
                )
                if hasattr(llm_instance, "invoke"):
                    resp = llm_instance.invoke(quick_prompt)
                    result = resp.content if hasattr(resp, "content") else str(resp)
                else:
                    resp = llm_instance(quick_prompt)
                    result = str(resp)
                result = clean_answer_ultra_fast(result)
                cache_response(message_text, result, is_fast=True)
                return result
            except Exception as e:
                logger.error(f"❌ Ultra fast LLM error: {e}")
                return get_emergency_response_ultra_fast(message_text)

        return get_emergency_response_ultra_fast(message_text)

    except Exception as e:
        logger.error(f"💥 Ultra fast RAG query error: {e}")
        return get_emergency_response_ultra_fast(message_text)

# --- メイン超高速処理 ---
async def process_message_ultra_fast(message_text: str, user_id: str) -> str:
    """超高速メッセージ処理（数十秒以内を目標）"""
    logger.info(f"🚀 Ultra fast processing: {user_id}: '{message_text[:30]}...'")
    try:
        # 1) 超高速キャッシュ
        cached = get_cached_response(message_text)
        if cached:
            logger.info("⚡ Ultra fast cache hit - instant response")
            monitor.track_fast_response()
            return cached

        # 2) 超高速アクション判定
        action = detect_richmenu_action_ultra_fast(message_text)

        # 3) 定型応答（超高速）
        if action != "general":
            resp = get_richmenu_response_ultra_fast(action, user_id)
            cache_response(message_text, resp, is_fast=True)
            logger.info(f"⚡ Ultra fast richmenu response: {action}")
            monitor.track_fast_response()
            return resp

        # 4) RAG/LLM（超高速版）
        return await process_rag_query_ultra_fast(message_text, user_id)

    except Exception as e:
        logger.error(f"❌ Ultra fast processing error: {e}")
        return get_emergency_response_ultra_fast(message_text)

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
# イベントハンドラ（超高速版）
# ==============================================================================

if LINE_SDK_AVAILABLE and handler:

    @handler.add(MessageEvent, message=TextMessageContent)
    def handle_text_message(event):
        """超高速版：3秒タイムアウトで即応（大幅短縮）"""
        start = datetime.now()
        try:
            user_id = event.source.user_id
            message_text = event.message.text
            logger.info(f"📱 Ultra fast message from {user_id}: '{message_text[:100]}...'")

            # 別スレッドで asyncio イベントループ作成
            def _process_in_thread():
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    ans = loop.run_until_complete(process_message_ultra_fast(message_text, user_id))
                    loop.close()
                    return ans
                except Exception as e:
                    logger.error(f"Ultra fast thread error: {e}")
                    return get_emergency_response_ultra_fast(message_text)

            # 3秒タイムアウト（大幅短縮）
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(_process_in_thread)
                try:
                    answer = future.result(timeout=3)  # 5秒→3秒に短縮
                except concurrent.futures.TimeoutError:
                    logger.error("❌ Ultra fast processing timeout (3s)")
                    answer = "処理中です。もう一度お試しください。"

            send_ok = send_line_reply_safe(event.reply_token, answer)
            dur = (datetime.now() - start).total_seconds()

            monitor.log_webhook_event(
                "message",
                send_ok,
                {
                    "user_id": user_id,
                    "processing_time": dur,
                    "message_len": len(message_text),
                    "response_len": len(answer),
                    "ultra_fast": True,
                },
            )
            logger.info(f"✅ Ultra fast reply sent={send_ok} time={dur:.2f}s")

        except Exception as e:
            dur = (datetime.now() - start).total_seconds()
            logger.error(f"❌ Ultra fast message handler error: {e}")
            logger.error(traceback.format_exc())
            monitor.log_webhook_event(
                "message",
                False,
                {
                    "error": str(e),
                    "type": type(e).__name__,
                    "processing_time": dur,
                },
            )
            try:
                emergency = get_emergency_response_ultra_fast("")
                send_line_reply_safe(event.reply_token, emergency)
                logger.info("🆘 Emergency response sent")
            except Exception as final_error:
                logger.error(f"💥 Final emergency error: {final_error}")

    @handler.add(PostbackEvent)
    def handle_postback(event):
        """Postback超高速処理（新メッセージ対応）"""
        start = datetime.now()
        try:
            user_id = event.source.user_id
            postback_data = event.postback.data or ""
            logger.info(f"🔙 Ultra fast postback from {user_id}: {postback_data}")

            # data=action=xxx&source=...
            params = {}
            try:
                parts = [kv for kv in postback_data.split("&") if "=" in kv]
                params = dict(p.split("=", 1) for p in parts)
            except Exception as e:
                logger.error(f"Postback parse error: {e}")
                params = {"action": "unknown"}

            action = params.get("action", "unknown")

            # 超高速版の新メッセージ応答
            response_text = get_richmenu_response_ultra_fast(action, user_id)

            send_ok = send_line_reply_safe(event.reply_token, response_text)
            dur = (datetime.now() - start).total_seconds()
            monitor.log_webhook_event("postback", send_ok, {
                "user_id": user_id, 
                "action": action, 
                "processing_time": dur,
                "ultra_fast": True
            })
            monitor.track_fast_response()
            
        except Exception as e:
            dur = (datetime.now() - start).total_seconds()
            logger.error(f"💥 Ultra fast postback handler error: {e}")
            monitor.log_webhook_event("postback", False, {"error": str(e), "processing_time": dur})

    @handler.add(FollowEvent)
    def handle_follow(event):
        try:
            user_id = event.source.user_id
            welcome = (
                "🎉 友達追加ありがとうございます！\n\n"
                "キノエデザインの住まいAIコンシェルジュです。\n"
                "画面下のメニューから各種サービスをご利用いただけます。\n\n"
                "🤖 AI相談 / 📋 資料請求 / 📍 展示場予約 / 💰 資金計画 / 💬 チャット相談"
            )
            send_ok = send_line_reply_safe(event.reply_token, welcome)
            monitor.log_webhook_event("follow", send_ok, {"user_id": user_id})
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
        "performance_metrics": {
            "fast_responses": monitor.stats["fast_responses"],
            "fast_cache_size": len(_fast_cache),
            "regular_cache_size": len(_response_cache),
            "cache_capacity": MAX_CACHE_SIZE,
        },
        "system_info": {
            "timestamp": datetime.now().isoformat(),
            "ultra_fast_mode": True,
            "timeout_settings": {
                "message_processing": "3s",
                "rag_processing": "5s",
                "llm_processing": "optimized"
            }
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
        "ultra_fast_enabled": True,
        "performance_mode": "optimized",
        "timestamp": datetime.now().isoformat(),
    }

@router.post("/test")
async def test_line_bot():
    """簡易テスト：超高速経路で応答を生成"""
    if not handler:
        return {"status": "error", "message": "LINE Bot not configured"}
    try:
        test_message = "AI相談"
        test_user_id = "test-user"
        start_time = datetime.now()
        res = await process_message_ultra_fast(test_message, test_user_id)
        processing_time = (datetime.now() - start_time).total_seconds()
        
        return {
            "status": "success",
            "test_message": test_message,
            "test_response": res[:200] + "..." if len(res) > 200 else res,
            "response_length": len(res),
            "processing_time_seconds": processing_time,
            "ultra_fast_cache_size": len(_fast_cache),
            "regular_cache_size": len(_response_cache),
            "performance_mode": "ultra_fast",
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {"status": "error", "error": str(e), "timestamp": datetime.now().isoformat()}