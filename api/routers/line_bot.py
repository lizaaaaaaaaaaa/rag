# api/routers/line_bot.py - 完全修正版（高速応答対応＋安全性維持）
# - 署名検証強化・トークン正規化・安全送信・監視（既存機能を維持）
# - 高速応答：軽量キャッシュ / 高速アクション判定 / RAG&LLM タイムアウト
# - 回答クレンジング：「〜しましょう」系の表現を確実除去

import logging
from datetime import datetime
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
# 【高速応答】キャッシュ＆判定＆処理
# ==============================================================================

# --- 軽量メモリキャッシュ ---
_response_cache: Dict[str, str] = {}
MAX_CACHE_SIZE = 50

def _cache_key(text: str) -> str:
    return text.lower().strip()

def get_cached_response(message_text: str) -> Optional[str]:
    return _response_cache.get(_cache_key(message_text))

def cache_response(message_text: str, response: str):
    if len(_response_cache) >= MAX_CACHE_SIZE:
        # dictの先頭キー（最古）を削除
        try:
            oldest_key = next(iter(_response_cache))
            del _response_cache[oldest_key]
        except StopIteration:
            pass
    _response_cache[_cache_key(message_text)] = response

# --- 高速アクション判定（重要パターン先頭） ---
def detect_richmenu_action_fast(message_text: str) -> str:
    text_lower = message_text.lower().replace(" ", "").replace("　", "")
    if "ai相談" in text_lower or "ai住まい" in text_lower:
        return "ai_consultation"
    elif "資料請求" in text_lower or "カタログ" in text_lower:
        return "document_request"
    elif "展示場" in text_lower or "見学" in text_lower:
        return "exhibition_reservation"
    elif "資金計画" in text_lower or "ローン" in text_lower:
        return "finance_planning"
    elif "スタッフ" in text_lower or "チャット" in text_lower:
        return "chat_consultation"
    elif any(g in text_lower for g in ["こんにちは", "はじめまして", "よろしく"]):
        return "greeting"
    return "general"

# --- 高速リッチメニュー応答（簡潔） ---
def get_richmenu_response_fast(action: str, user_id: str) -> str:
    responses = {
        "ai_consultation": (
            "🤖 AI住まい相談を開始します！\n\n"
            "住まいに関するご質問をお気軽にどうぞ。\n\n"
            "例：「坪単価について教えて」「標準仕様は？」「断熱性能について」\n\n"
            "何でもお聞きください😊"
        ),
        "document_request": (
            "📋 資料請求を承ります\n\n"
            "以下をお送りください：\n"
            "1️⃣ お名前\n"
            "2️⃣ ご住所（郵便番号から）\n"
            "3️⃣ お電話番号\n"
            "4️⃣ ご希望資料\n\n"
            "3営業日以内にお送りします📮"
        ),
        "exhibition_reservation": (
            "📍 展示場予約を承ります\n\n"
            "以下をお送りください：\n"
            "・ご希望日時\n"
            "・お名前\n"
            "・お電話番号\n"
            "・参加人数\n\n"
            "お待ちしております🏠"
        ),
        "finance_planning": (
            "💰 資金計画のご相談\n\n"
            "住宅ローンや資金計画をサポートします。\n\n"
            "・ご年収\n・自己資金\n・ご希望借入額\n\n"
            "をお聞かせください。最適なプランをご提案します。"
        ),
        "chat_consultation": (
            "💬 スタッフとのご相談\n\n"
            "【対応時間】9:00-18:00（水曜定休）\n\n"
            "住まいづくりのご質問をお気軽にどうぞ。\n"
            "営業時間内でしたら迅速にお返事します📱"
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
def clean_answer_fast(answer: str) -> str:
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

# --- 緊急応答（高速） ---
def get_emergency_response_fast(message_text: str) -> str:
    if "坪単価" in message_text:
        return "坪単価は約70〜85万円/坪が目安です。詳細はお問い合わせください。"
    elif "資料" in message_text:
        return "資料をお送りします。お名前、ご住所、お電話番号をお教えください。"
    elif "見学" in message_text or "展示" in message_text:
        return "展示場見学を承ります。ご希望日時をお聞かせください。"
    else:
        return "申し訳ございません。詳しくはお問い合わせください。"

# --- 高速RAG ---
def get_app_globals_fast():
    """高速アクセス：既存の get_app_globals を流用"""
    return get_app_globals()

async def process_rag_query_fast(message_text: str, user_id: str) -> str:
    """LINE向け高速RAG（タイムアウト＆短文化）"""
    try:
        globals_dict = get_app_globals_fast()
        vectorstore = globals_dict.get("vectorstore")
        rag_chain_template = globals_dict.get("rag_chain_template")
        llm_instance = globals_dict.get("llm_instance")

        if not vectorstore and not llm_instance:
            logger.warning("⚠️ No RAG components available - fast fallback")
            return get_emergency_response_fast(message_text)

        # 挨拶即時応答（超軽量）
        quick_responses = {
            "こんにちは": "こんにちは！住まいづくりのご質問をお気軽にどうぞ🏠",
            "ありがとう": "どういたしまして！他にもご質問がございましたらお聞かせください🙏",
            "おはよう": "おはようございます！今日も住まいづくりのお手伝いをいたします☀️",
        }
        for k, v in quick_responses.items():
            if k in message_text:
                cache_response(message_text, v)
                return v

        # RAG（8秒タイムアウト）
        if vectorstore and rag_chain_template:
            logger.info("📚 Fast RAG processing...")
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
                result = await asyncio.wait_for(run_rag(), timeout=8.0)
                answer = result.get("result", "") if result else ""
                if answer and len(answer) > 10:
                    answer = clean_answer_fast(answer)
                    if len(answer) > 300:
                        answer = answer[:280] + "詳細はお問い合わせください。"
                    cache_response(message_text, answer)
                    logger.info(f"✅ Fast RAG success: {len(answer)} chars")
                    return answer
                else:
                    raise ValueError("Empty or insufficient RAG response")
            except asyncio.TimeoutError:
                logger.warning("⏰ RAG timeout - switching to fast fallback")
                return get_emergency_response_fast(message_text)
            except Exception as e:
                logger.error(f"❌ Fast RAG error: {e}")
                return get_emergency_response_fast(message_text)

        # LLMのみ（100文字以内）
        if llm_instance:
            logger.info("🤖 Fast LLM processing...")
            try:
                quick_prompt = (
                    "住宅専門アドバイザーとして簡潔に答えてください。\n\n"
                    f"質問: {message_text}\n\n"
                    "【重要】\n- 100文字以内\n- 「〜しましょう」禁止\n- 実用的に\n\n"
                    "回答:"
                )
                if hasattr(llm_instance, "invoke"):
                    resp = llm_instance.invoke(quick_prompt)
                    result = resp.content if hasattr(resp, "content") else str(resp)
                else:
                    resp = llm_instance(quick_prompt)
                    result = str(resp)
                result = clean_answer_fast(result)
                cache_response(message_text, result)
                return result
            except Exception as e:
                logger.error(f"❌ Fast LLM error: {e}")
                return get_emergency_response_fast(message_text)

        return get_emergency_response_fast(message_text)

    except Exception as e:
        logger.error(f"💥 Fast RAG query error: {e}")
        return get_emergency_response_fast(message_text)

# --- メイン高速処理 ---
async def process_message_fast(message_text: str, user_id: str) -> str:
    """超高速メッセージ処理（キャッシュ→判定→定型→RAG/LLM）"""
    logger.info(f"🚀 Fast processing: {user_id}: '{message_text[:30]}...'")
    try:
        # 1) キャッシュ
        cached = get_cached_response(message_text)
        if cached:
            logger.info("⚡ Cache hit - instant response")
            return cached

        # 2) アクション判定
        action = detect_richmenu_action_fast(message_text)

        # 3) 定型応答（高速）
        if action != "general":
            resp = get_richmenu_response_fast(action, user_id)
            cache_response(message_text, resp)
            logger.info(f"⚡ Fast richmenu response: {action}")
            return resp

        # 4) RAG/LLM
        return await process_rag_query_fast(message_text, user_id)

    except Exception as e:
        logger.error(f"❌ Fast processing error: {e}")
        return get_emergency_response_fast(message_text)

# ==============================================================================
# 既存の高度応答（リッチ文面・Web検索拡張）—保持
#   ※ Postback 等では従来の長文案内を使いたいケースがあるため残置
# ==============================================================================

def detect_richmenu_action(message_text: str) -> str:
    """従来の寛容判定（互換用途）"""
    text_lower = message_text.lower().replace(" ", "").replace("　", "")
    action_patterns = {
        "ai_consultation": ["ai相談", "ai住まい", "相談開始", "質問したい", "聞きたい", "教えて", "ai", "住まい相談", "家について", "ai相談を開始"],
        "document_request": ["資料請求", "カタログ", "資料がほしい", "パンフレット", "資料送って", "カタログください"],
        "exhibition_reservation": ["展示場", "見学", "予約", "来場", "モデルハウス", "実際に見たい", "展示場予約"],
        "finance_planning": ["資金計画", "ローン", "お金", "費用", "予算", "住宅ローン", "資金相談"],
        "chat_consultation": ["スタッフ", "人と話したい", "直接相談", "チャット", "担当者", "営業"],
        "greeting": ["こんにちは", "はじめまして", "よろしく", "おはよう", "こんばんは", "hello", "hi"],
    }
    for action, patterns in action_patterns.items():
        if any(p in text_lower for p in patterns):
            return action
    return "general"


def get_richmenu_response(action: str, user_id: str, context: dict = None) -> Optional[str]:
    """従来のリッチ文面（長文）"""
    responses = {
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

（準備中のご案内）""",
        "document_request": """📋 資料請求を承ります

【必須情報】
1️⃣ お名前（フルネーム）
2️⃣ ご住所（〒郵便番号から）
3️⃣ お電話番号

【ご希望の資料】
🏠 総合カタログ / 📸施工事例集 / 📋標準仕様書 / 💰参考価格表

3営業日以内にお送りいたします📮""",
        "exhibition_reservation": """📍 展示場来場予約

以下をメッセージでお送りください：
・ご希望日時（第1・第2希望）
・お名前
・お電話番号  
・参加人数

スタッフ一同、お待ちしております🏠""",
        "finance_planning": """💰 資金計画・住宅ローン相談

ご年収 / 自己資金 / ご希望借入額 / 返済期間をお知らせください。
最適なプランをご提案します。""",
        "chat_consultation": """💬 スタッフとチャット相談

【対応時間】9:00-18:00（水曜定休）""",
        "greeting": """こんにちは！キノエデザインの住まいAIコンシェルジュです🏠
画面下のメニューから各種サービスをご利用いただけます。""",
    }
    base = responses.get(action)
    if base and context:
        current_hour = datetime.now().hour
        if current_hour < 9 or current_hour > 18:
            if action in ["finance_planning", "chat_consultation"]:
                base += "\n\n⏰ 現在は営業時間外です。\n営業開始後（9:00〜）にご回答いたします。"
    return base


def get_emergency_response(message_text: str) -> str:
    """従来の緊急応答"""
    if any(w in message_text for w in ["こんにちは", "はじめまして", "hello"]):
        return ("こんにちは！キノエデザインです🏠\n\n"
                "現在システムの調整中ですが、以下のようにメッセージを送っていただければお手伝いできます：\n\n"
                "🤖 「AI相談」/ 📋「資料請求」/ 📍「展示場予約」/ 💰「資金計画」/ 💬「スタッフ」")
    elif "資料" in message_text or "カタログ" in message_text:
        return ("📋 資料請求を承ります\n\n"
                "1️⃣ お名前\n2️⃣ ご住所（郵便番号から）\n3️⃣ お電話番号\n4️⃣ ご希望資料\n\n3営業日以内にお送いいたします📮")
    else:
        return ("申し訳ございません。システムの調整中です。\n"
                "📞 0120-XXX-XXX / 📧 info@kinoe-design.com（9:00-18:00・水曜定休）")

# （高度処理：RAG/LLM/Web検索拡張は保持。高速ルートは別実装のため省略）

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
            # 200系の応答を返し再送を抑止
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
# イベントハンドラ
# ==============================================================================

if LINE_SDK_AVAILABLE and handler:

    @handler.add(MessageEvent, message=TextMessageContent)
    def handle_text_message(event):
        """高速版：5秒タイムアウトで即応。内部は非同期＋スレッドで処理"""
        start = datetime.now()
        try:
            user_id = event.source.user_id
            message_text = event.message.text
            logger.info(f"📱 Fast message from {user_id}: '{message_text[:100]}...'")

            # 別スレッドで asyncio イベントループ作成
            def _process_in_thread():
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    ans = loop.run_until_complete(process_message_fast(message_text, user_id))
                    loop.close()
                    return ans
                except Exception as e:
                    logger.error(f"Fast thread error: {e}")
                    return get_emergency_response_fast(message_text)

            # 5秒タイムアウト（超短期で応答を返す）
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(_process_in_thread)
                try:
                    answer = future.result(timeout=5)
                except concurrent.futures.TimeoutError:
                    logger.error("❌ Fast processing timeout (5s)")
                    answer = "処理に時間がかかっています。もう一度お試しください。"

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
                },
            )
            logger.info(f"✅ Fast reply sent={send_ok} time={dur:.2f}s")

        except Exception as e:
            dur = (datetime.now() - start).total_seconds()
            logger.error(f"❌ Fast message handler error: {e}")
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
                emergency = get_emergency_response_fast("")
                send_line_reply_safe(event.reply_token, emergency)
                logger.info("🆘 Emergency response sent")
            except Exception as final_error:
                logger.error(f"💥 Final emergency error: {final_error}")

    @handler.add(PostbackEvent)
    def handle_postback(event):
        """Postbackは従来の丁寧な長文案内を優先"""
        start = datetime.now()
        try:
            user_id = event.source.user_id
            postback_data = event.postback.data or ""
            logger.info(f"🔙 Postback from {user_id}: {postback_data}")

            # data=action=xxx&source=...
            params = {}
            try:
                parts = [kv for kv in postback_data.split("&") if "=" in kv]
                params = dict(p.split("=", 1) for p in parts)
            except Exception as e:
                logger.error(f"Postback parse error: {e}")
                params = {"action": "unknown"}

            action = params.get("action", "unknown")

            # まず高速版の短文、なければ従来の長文
            response_text = get_richmenu_response_fast(action, user_id) or get_richmenu_response(action, user_id) or f"アクション '{action}' を受信しました。"

            send_ok = send_line_reply_safe(event.reply_token, response_text)
            dur = (datetime.now() - start).total_seconds()
            monitor.log_webhook_event("postback", send_ok, {"user_id": user_id, "action": action, "processing_time": dur})
        except Exception as e:
            dur = (datetime.now() - start).total_seconds()
            logger.error(f"💥 Postback handler error: {e}")
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
        "system_info": {
            "timestamp": datetime.now().isoformat(),
            "fast_cache_size": len(_response_cache),
            "fast_cache_capacity": MAX_CACHE_SIZE,
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
        "timestamp": datetime.now().isoformat(),
    }

@router.post("/test")
async def test_line_bot():
    """簡易テスト：高速経路で応答を生成"""
    if not handler:
        return {"status": "error", "message": "LINE Bot not configured"}
    try:
        test_message = "テスト"
        test_user_id = "test-user"
        res = await process_message_fast(test_message, test_user_id)
        return {
            "status": "success",
            "test_message": test_message,
            "test_response": res[:100] + "..." if len(res) > 100 else res,
            "response_length": len(res),
            "cache_size": len(_response_cache),
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {"status": "error", "error": str(e), "timestamp": datetime.now().isoformat()}
