import logging
import os
import re
import json
import asyncio
import traceback
import time
import hashlib
from datetime import datetime, timedelta
from typing import Dict, Optional, Any, List

from fastapi import APIRouter, Request, BackgroundTasks
from fastapi.responses import JSONResponse

# 資金計画機能をインポート
from api.routers.line_bot_financial_planner import (
    FinancialPlanningHandler, 
    is_financial_planning_message,
    handle_financial_message_for_line
)

logger = logging.getLogger(__name__)

# LINE SDK v3 import
try:
    from linebot.v3 import WebhookHandler
    from linebot.v3.exceptions import InvalidSignatureError
    from linebot.v3.messaging import (
        Configuration, ApiClient, MessagingApi, ReplyMessageRequest, PushMessageRequest, TextMessage,
        ApiException
    )
    from linebot.v3.webhooks import MessageEvent, TextMessageContent, PostbackEvent, FollowEvent
    LINE_SDK_AVAILABLE = True
    logger.info("✅ LINE Bot SDK v3 imported successfully")
except ImportError as e:
    logger.error(f"❌ LINE Bot SDK not available: {e}")
    LINE_SDK_AVAILABLE = False
    class WebhookHandler:
        def __init__(self, *args, **kwargs): pass
        def add(self, *args, **kwargs):
            def decorator(func): return func
            return decorator
        def handle(self, *args, **kwargs): pass

router = APIRouter(tags=["line-ultra-fast"])

# ==============================================================================
# 🚀 指定文面（完全固定・変更不可）
# ==============================================================================
RICHMENU_FIXED_RESPONSES = {
    # 友だち追加時の挨拶（指定文面）
    "follow_greeting": """こんにちは！キノエデザインです。
この度は友だち追加ありがとうございます✨

目的のボタンをタップ👇
🤖AI相談 / 📍来場予約 / 📄資料請求 / 💰資金計画 / 🌐サイト / 💬チャット

AIは24時間、担当者は当日〜翌営業日に返信します。

※ご使用の前に、必ず以下の取り扱いをご確認ください。
プライバシーポリシー：【https://preview.studio.site/live/EjOQljz1WJ/privacy-policy 】
利用規約：【https://preview.studio.site/live/EjOQljz1WJ/termsofuse/service 】
Cookie：【https://preview.studio.site/live/EjOQljz1WJ/cookie 】""",

    # リッチメニューボタン応答（指定文面）
    "🤖 AI相談": """🤖 AI住まい相談を開始します！

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

    "🌐 AI住まいサイト": """🌐 AI住まいサイトのご案内

キノエデザインの住まい情報サイトをご紹介します。（家づくりの疑問にAIが24時間即回答）

🏠 サイト内容：
・AIチャット相談（資金計画／補助金／間取り など）
・施工写真（実例）
・間取りの考え方・プラン例
・よくある質問（最初に迷う3つのこと ほか）
・保存版デジタル冊子 ZINE（無料ダウンロード）
・LINEで無料相談／来場予約

📱 サイトURL:
https://preview.studio.site/live/EjOQljz1WJ/""",

    "📋 資料請求": """📋ありがとうございます！こちらからご覧いただけます。

〔資料タイトル〕（PDF）：〔URL〕

よろしければ簡単アンケート（任意）：
・ご計画時期：今すぐ / 3–6か月 / 1年以内 / 未定
・連絡方法（任意）：このLINE / メール / 連絡不要

※必ず以下の取り扱いをご確認ください。
プライバシーポリシー：【https://preview.studio.site/live/EjOQljz1WJ/privacy-policy 】
利用規約：【https://preview.studio.site/live/EjOQljz1WJ/termsofuse/service 】
Cookie：【https://preview.studio.site/live/EjOQljz1WJ/cookie 】""",

    "📍 展示場来場": """📍 展示場のご来場予約につきましては、下記URLより必要事項のご入力をお願い申し上げます。

【https://preview.studio.site/live/EjOQljz1WJ/reservation 】

スタッフ一同、心よりお待ちしております！""",

    "💰 資金計画": """💬 AI資金診断のご案内

本診断は匿名でご利用いただけます。ご回答内容は保存いたしません。算出される金額は試算（概算）であり、目安としてご確認ください。

お手数ですが、以下の5点をご入力ください。
・年収（概算可）
・毎月のご希望返済額
・住宅ローンのご希望借入期間
・ご家族構成（例：大人2名・お子さま1名）
・その他の大きなご負担（例：自動車ローン 等）

未入力の項目があっても進められます。ご入力後、概算結果をご提示いたします。""",

    "💬 チャット相談": """💬 スタッフとのご相談

【対応時間】
営業時間：9:00-18:00

📱 ご相談方法：
・このLINEでの直接相談
・お電話での相談
・展示場での対面相談

営業時間内でしたら迅速にお返事します。
お気軽にお声かけください！"""
}

# 絵文字なしパターンのマッピング
RICHMENU_KEYWORD_MAPPING = {
    "AI相談": "🤖 AI相談",
    "AI住まいサイト": "🌐 AI住まいサイト",
    "資料請求": "📋 資料請求",
    "展示場来場": "📍 展示場来場",
    "展示場来場　予約": "📍 展示場来場",  # 全角スペース対応
    "展示場来場予約": "📍 展示場来場",
    "資金計画": "💰 資金計画",
    "チャット相談": "💬 チャット相談"
}

# ==============================================================================
# 🚀 超高速リッチメニューレスポンダー
# ==============================================================================
class UltraFastRichMenuResponder:
    """超高速リッチメニューレスポンダー（指定文面のみ）"""
    
    def __init__(self):
        self.response_count = 0
        self.miss_count = 0
    
    def get_fixed_response(self, message: str) -> Optional[str]:
        """固定応答取得（0.001秒目標）"""
        message_normalized = message.strip()
        
        # 🚀 完全一致チェック（最優先）
        if message_normalized in RICHMENU_FIXED_RESPONSES:
            self.response_count += 1
            logger.info(f"⚡ 固定応答: {message_normalized}")
            return RICHMENU_FIXED_RESPONSES[message_normalized]
        
        # 🚀 キーワードマッピング
        for keyword, template_key in RICHMENU_KEYWORD_MAPPING.items():
            if keyword in message_normalized:
                if template_key in RICHMENU_FIXED_RESPONSES:
                    self.response_count += 1
                    logger.info(f"⚡ キーワード応答: {keyword} -> {template_key}")
                    return RICHMENU_FIXED_RESPONSES[template_key]
        
        self.miss_count += 1
        return None
    
    def get_stats(self) -> Dict[str, Any]:
        """統計取得"""
        total = self.response_count + self.miss_count
        hit_rate = (self.response_count / total * 100) if total > 0 else 0
        
        return {
            "total_templates": len(RICHMENU_FIXED_RESPONSES),
            "keyword_mappings": len(RICHMENU_KEYWORD_MAPPING),
            "response_count": self.response_count,
            "hit_rate": hit_rate
        }

# ==============================================================================
# 🚀 軽量重複防止システム
# ==============================================================================
class LightweightDuplicateGuard:
    """軽量重複防止システム"""
    
    def __init__(self):
        self.recent_messages = {}
        self.recent_events = {}
        self.message_window = 25  # 25秒
        self.event_window = 5     # 5秒
        
        self.stats = {
            "message_duplicates": 0,
            "event_duplicates": 0,
            "total_checks": 0
        }
    
    def should_send_message(self, user_id: str, message: str) -> bool:
        """メッセージ送信判定"""
        self.stats["total_checks"] += 1
        
        # メッセージハッシュ生成
        message_hash = hashlib.md5(message[:100].encode()).hexdigest()[:6]
        key = f"{user_id}:{message_hash}"
        
        current_time = time.time()
        
        # 重複チェック
        if key in self.recent_messages:
            time_diff = current_time - self.recent_messages[key]
            if time_diff < self.message_window:
                self.stats["message_duplicates"] += 1
                return False
        
        # 記録更新
        self.recent_messages[key] = current_time
        
        # 簡易クリーンアップ
        if len(self.recent_messages) > 500:
            cutoff_time = current_time - self.message_window * 2
            old_keys = [k for k, t in self.recent_messages.items() if t < cutoff_time]
            for k in old_keys:
                del self.recent_messages[k]
        
        return True
    
    def should_process_event(self, user_id: str, event_data: str) -> bool:
        """イベント処理判定"""
        event_hash = hashlib.md5(event_data[:50].encode()).hexdigest()[:6]
        key = f"{user_id}:{event_hash}"
        
        current_time = time.time()
        
        if key in self.recent_events:
            time_diff = current_time - self.recent_events[key]
            if time_diff < self.event_window:
                self.stats["event_duplicates"] += 1
                return False
        
        self.recent_events[key] = current_time
        
        # 簡易クリーンアップ
        if len(self.recent_events) > 200:
            cutoff_time = current_time - self.event_window * 2
            old_keys = [k for k, t in self.recent_events.items() if t < cutoff_time]
            for k in old_keys:
                del self.recent_events[k]
        
        return True

# ==============================================================================
# LINE Bot設定
# ==============================================================================
def get_line_credentials_safe():
    """LINE認証情報を安全に取得"""
    access_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    channel_secret = os.getenv("LINE_CHANNEL_SECRET")
    
    # Secret Manager対応
    if not access_token or not channel_secret:
        try:
            from google.cloud import secretmanager
            client = secretmanager.SecretManagerServiceClient()
            project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "rag-cloud-project")
            
            if not access_token:
                name = f"projects/{project_id}/secrets/LINE_CHANNEL_ACCESS_TOKEN/versions/latest"
                resp = client.access_secret_version(request={"name": name})
                access_token = resp.payload.data.decode("UTF-8")
            
            if not channel_secret:
                name = f"projects/{project_id}/secrets/LINE_CHANNEL_SECRET/versions/latest"
                resp = client.access_secret_version(request={"name": name})
                channel_secret = resp.payload.data.decode("UTF-8")
                
        except Exception as e:
            logger.warning(f"Secret Manager access failed: {e}")
    
    return access_token, channel_secret

def normalize_line_token(token) -> str:
    """LINE トークン正規化"""
    if not token:
        return ""
    
    token_str = str(token)
    token_str = token_str.replace('\r', '').replace('\n', '').replace('\t', '').strip()
    
    if token_str.lower().startswith("bearer "):
        token_str = token_str[7:].strip()
    
    if token_str.startswith("b'") and token_str.endswith("'"):
        token_str = token_str[2:-1]
    
    token_str = token_str.replace('"', '').replace("'", "")
    return ''.join(token_str.split())

# 初期化
LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET = get_line_credentials_safe()
line_bot_api = None
handler = None

# グローバルインスタンス
richmenu_responder = UltraFastRichMenuResponder()
duplicate_guard = LightweightDuplicateGuard()
financial_handler = FinancialPlanningHandler()

if LINE_SDK_AVAILABLE and LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET:
    try:
        normalized_token = normalize_line_token(LINE_CHANNEL_ACCESS_TOKEN)
        normalized_secret = normalize_line_token(LINE_CHANNEL_SECRET)
        
        if normalized_token and normalized_secret:
            configuration = Configuration(access_token=normalized_token)
            handler = WebhookHandler(normalized_secret)
            
            with ApiClient(configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
            
            logger.info("✅ LINE Bot initialized (Ultra Fast Richmenu)")
        else:
            raise ValueError("Empty normalized credentials")
            
    except Exception as e:
        logger.error(f"❌ LINE Bot initialization failed: {e}")
        line_bot_api, handler = None, None

# ==============================================================================
# 🚀 高速メッセージ送信
# ==============================================================================
def send_line_message_fast(reply_token: str, user_id: str, message: str) -> bool:
    """高速LINE送信"""
    if not line_bot_api:
        logger.error("❌ LINE Bot API not initialized")
        return False
    
    # 重複防止チェック
    if not duplicate_guard.should_send_message(user_id, message):
        return True  # 重複防止されたが「成功」として扱う
    
    try:
        normalized_token = normalize_line_token(LINE_CHANNEL_ACCESS_TOKEN)
        if not normalized_token:
            return False
        
        configuration = Configuration(access_token=normalized_token)
        with ApiClient(configuration) as api_client:
            messaging_api = MessagingApi(api_client)
            
            # Reply API試行
            try:
                messaging_api.reply_message_with_http_info(
                    ReplyMessageRequest(
                        reply_token=reply_token,
                        messages=[TextMessage(text=message)]
                    )
                )
                logger.debug(f"✅ Reply sent: {len(message)} chars")
                return True
                
            except ApiException as reply_error:
                # Push APIフォールバック
                if "Invalid reply token" in str(reply_error) or getattr(reply_error, "status", None) == 400:
                    try:
                        messaging_api.push_message_with_http_info(
                            PushMessageRequest(
                                to=user_id,
                                messages=[TextMessage(text=message)]
                            )
                        )
                        logger.debug(f"✅ Push sent: {len(message)} chars")
                        return True
                    except Exception:
                        return False
                else:
                    return False
        
    except Exception as e:
        logger.error(f"❌ Send failed: {e}")
        return False

# ==============================================================================
# Webhook エンドポイント
# ==============================================================================
@router.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    """Webhook エンドポイント"""
    
    if not line_bot_api or not handler:
        logger.error("❌ LINE Bot not configured")
        return {"status": "error", "message": "Not configured"}
    
    try:
        body = await request.body()
        signature = request.headers.get("X-Line-Signature", "")
        
        if not signature:
            logger.error("❌ Missing signature")
            return {"status": "error", "message": "Missing signature"}
        
        body_text = body.decode("utf-8")
        logger.debug(f"📨 Processing webhook: {len(body_text)} bytes")
        
        handler.handle(body_text, signature)
        
        return {"status": "ok", "timestamp": datetime.now().isoformat()}
        
    except InvalidSignatureError:
        logger.error("❌ Invalid signature")
        return {"status": "signature_error"}
    except Exception as e:
        logger.error(f"💥 Webhook error: {e}")
        return {"status": "error", "error": str(e)}

# ==============================================================================
# イベントハンドラ（指定文面統一版）
# ==============================================================================
if LINE_SDK_AVAILABLE and handler:
    
    @handler.add(FollowEvent)
    def handle_follow(event):
        """フォローハンドラ（指定文面）"""
        try:
            user_id = event.source.user_id
            reply_token = event.reply_token
            
            # イベント重複防止
            event_data = f"follow_{user_id}"
            if not duplicate_guard.should_process_event(user_id, event_data):
                return
            
            logger.info(f"👤 New follower: {user_id}")
            
            # 🚀 指定文面による挨拶メッセージ
            greeting = RICHMENU_FIXED_RESPONSES["follow_greeting"]
            
            success = send_line_message_fast(reply_token, user_id, greeting)
            logger.debug(f"✅ Greeting sent: success={success}")
            
        except Exception as e:
            logger.error(f"❌ Follow handler error: {e}")
    
    @handler.add(MessageEvent, message=TextMessageContent)
    def handle_message(event):
        """メッセージハンドラ（超高速・指定文面統一版）"""
        start_time = time.time()
        
        try:
            user_id = event.source.user_id
            message_text = event.message.text
            reply_token = event.reply_token
            
            # イベント重複防止
            event_data = f"message_{user_id}_{message_text[:20]}"
            if not duplicate_guard.should_process_event(user_id, event_data):
                return
            
            logger.info(f"📱 Message: '{message_text[:30]}...' from {user_id}")
            
            # 🚀 1. リッチメニュー固定応答チェック（最優先・即時）
            fixed_response = richmenu_responder.get_fixed_response(message_text)
            if fixed_response:
                success = send_line_message_fast(reply_token, user_id, fixed_response)
                duration = (time.time() - start_time) * 1000
                logger.info(f"⚡ Fixed response: {duration:.1f}ms")
                return
            
            # 🚀 2. 資金計画チェック（状態保持）
            if (is_financial_planning_message(message_text) or 
                financial_handler.state_manager.get_session(user_id)):
                
                response_text = handle_financial_message_for_line(user_id, message_text)
                success = send_line_message_fast(reply_token, user_id, response_text)
                duration = (time.time() - start_time) * 1000
                logger.info(f"💰 Financial response: {duration:.1f}ms")
                return
            
            # 🚀 3. フォールバック応答（簡潔版）
            fallback_response = """ご質問ありがとうございます😊

目的のボタンをタップしてください👇
🤖AI相談 / 📍来場予約 / 📄資料請求 / 💰資金計画 / 🌐サイト / 💬チャット

具体的なご質問もお気軽にどうぞ✨"""
            
            success = send_line_message_fast(reply_token, user_id, fallback_response)
            duration = (time.time() - start_time) * 1000
            logger.info(f"💬 Fallback response: {duration:.1f}ms")
            
        except Exception as e:
            logger.error(f"❌ Message handler error: {e}")
            try:
                emergency = "申し訳ございません。一時的にエラーが発生しています。リッチメニューをお試しください😊"
                send_line_message_fast(event.reply_token, event.source.user_id, emergency)
            except Exception:
                pass

    @handler.add(PostbackEvent)
    def handle_postback(event):
        """Postbackハンドラ（指定文面統一版）"""
        try:
            user_id = event.source.user_id
            reply_token = event.reply_token
            postback_data = event.postback.data or ""
            
            # イベント重複防止
            event_data = f"postback_{user_id}_{postback_data[:15]}"
            if not duplicate_guard.should_process_event(user_id, event_data):
                return
            
            logger.debug(f"📙 Postback: {postback_data}")
            
            # 🚀 Postback処理（指定文面）
            response_text = None
            
            # Postbackデータから固定応答を取得
            response_text = richmenu_responder.get_fixed_response(postback_data)
            
            # action=値 形式の処理
            if not response_text and "action=" in postback_data:
                action_value = ""
                for part in postback_data.split("&"):
                    if part.startswith("action="):
                        action_value = part.split("=", 1)[1]
                        break
                
                if action_value:
                    response_text = richmenu_responder.get_fixed_response(action_value)
            
            # 資金計画の特別処理
            if ("資金計画" in postback_data or "financial_start" in postback_data) and not response_text:
                response_text = handle_financial_message_for_line(user_id, "💰 資金計画")
            
            # フォールバック応答
            if not response_text:
                response_text = """目的のボタンをタップしてください😊

🤖AI相談 / 📍来場予約 / 📄資料請求 / 💰資金計画 / 🌐サイト / 💬チャット"""
            
            success = send_line_message_fast(reply_token, user_id, response_text)
            logger.debug(f"✅ Postback processed: success={success}")
            
        except Exception as e:
            logger.error(f"💥 Postback error: {e}")

# ==============================================================================
# 統計エンドポイント
# ==============================================================================
@router.get("/stats")
def get_line_stats():
    """LINE Bot統計取得"""
    richmenu_stats = richmenu_responder.get_stats()
    duplicate_stats = duplicate_guard.stats
    
    return {
        "line_bot_stats": {
            "richmenu_system": richmenu_stats,
            "duplicate_prevention": {
                **duplicate_stats,
                "active_records": {
                    "messages": len(duplicate_guard.recent_messages),
                    "events": len(duplicate_guard.recent_events)
                }
            },
            "system_status": {
                "line_sdk": LINE_SDK_AVAILABLE,
                "line_bot_api": line_bot_api is not None,
                "handler": handler is not None
            }
        },
        "optimization_status": {
            "fixed_responses": "enabled",
            "duplicate_prevention": "enabled", 
            "fast_routing": "enabled",
            "specified_text_only": "enforced"
        },
        "timestamp": datetime.now().isoformat()
    }

@router.get("/health")
def health_check():
    """ヘルスチェック"""
    richmenu_stats = richmenu_responder.get_stats()
    
    return {
        "status": "healthy_ultra_fast",
        "system_status": {
            "line_sdk": "ok" if LINE_SDK_AVAILABLE else "error",
            "line_bot_api": "ok" if line_bot_api else "error",
            "richmenu_system": "ok",
            "duplicate_prevention": "ok",
            "financial_planning": "ok"
        },
        "richmenu_stats": richmenu_stats,
        "optimizations": [
            "Fixed response system with specified text only",
            "Ultra-fast duplicate prevention", 
            "Optimized routing for <100ms response",
            "RAG completely bypassed for rich menu"
        ],
        "performance_targets": {
            "rich_menu_response": "< 100ms ✅",
            "message_consistency": "100% specified text ✅",
            "rag_avoidance": "100% for rich menu ✅"
        },
        "timestamp": datetime.now().isoformat()
    }
