# api/routers/line_bot_rag_integrated.py - RAG統合対応版LINE Bot

import logging
import os
import re
import json
import asyncio
import traceback
import time
import hashlib
import concurrent.futures  # 追加: concurrent.futuresのインポート
from datetime import datetime
from typing import Dict, Optional, Any, List

from fastapi import APIRouter, Request, BackgroundTasks
from fastapi.responses import JSONResponse

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

router = APIRouter(tags=["line-rag-integrated"])

# ==============================================================================
# LINE Bot設定と初期化
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

if LINE_SDK_AVAILABLE and LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET:
    try:
        normalized_token = normalize_line_token(LINE_CHANNEL_ACCESS_TOKEN)
        normalized_secret = normalize_line_token(LINE_CHANNEL_SECRET)
        
        if normalized_token and normalized_secret:
            configuration = Configuration(access_token=normalized_token)
            handler = WebhookHandler(normalized_secret)
            
            with ApiClient(configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
            
            logger.info("✅ RAG-integrated LINE Bot initialized successfully")
        else:
            raise ValueError("Empty normalized credentials")
            
    except Exception as e:
        logger.error(f"❌ LINE Bot initialization failed: {e}")
        line_bot_api, handler = None, None

# ==============================================================================
# RAG統合応答生成クラス
# ==============================================================================
class LineRAGIntegration:
    def __init__(self):
        self.greeting_message = self._load_greeting_message()
        self.richmenu_responses = self._load_richmenu_responses()
        self.performance_stats = {
            "total_messages": 0,
            "richmenu_responses": 0,
            "rag_queries": 0,
            "greeting_sent": 0,
            "push_fallbacks": 0
        }
    
    def _load_greeting_message(self) -> str:
        """友だち追加時の挨拶メッセージ"""
        return """こんにちは！キノエデザインです。
この度は友だち追加ありがとうございます✨

目的のボタンをタップ👇
🤖AI相談 / 📍来場予約 / 📄資料請求 / 💴資金計画 / 🌐サイト / 💬チャット

AIは24時間、担当者は当日〜翌営業日に返信します。

取扱い(プライバシーポリシー)：〔https://preview.studio.site/live/EjOQljz1WJ/privacy-policy〕"""
    
    def _load_richmenu_responses(self) -> Dict[str, str]:
        """リッチメニュー専用応答（基本的なメニュー表示のみ）"""
        return {
            "AI相談": """🤖 AI住まい相談を開始します！

キノエデザインの住まいAIコンシェルジュです。
住まいに関するご質問をお気軽にどうぞ！

💡 例えば：
・坪単価について教えて
・標準仕様はどんな感じ？
・耐震性能について知りたい
・断熱性能はどのくらい？

何でもお聞きください😊""",

            "AI住まいサイト": """🌐 AI住まいサイトのご案内

キノエデザインの住まい情報サイトをご紹介します。

🏠 サイト内容：
・施工事例・間取りプラン
・住宅性能・標準仕様
・価格・坪単価情報
・お客様の声

📱 サイトURL:
https://kinoe-design.com

詳しい住まい情報をご確認いただけます！""",

            "資料請求": """📋 資料請求を承ります

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

3営業日以内にお送りいたします！""",

            "展示場来場予約": """📍 展示場来場予約を承ります

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

            "資金計画": """💰 資金計画・住宅ローン相談

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

最適なプランをご提案いたします！""",

            "チャット相談": """💬 スタッフとのご相談

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
お気軽にお声かけください！"""
        }
    
    def detect_richmenu_action(self, message_text: str) -> str:
        """リッチメニューアクション検出（限定的）"""
        text_clean = message_text.lower().replace(" ", "").replace("　", "")
        
        # 非常に限定的なキーワードのみリッチメニュー応答
        richmenu_keywords = {
            "ai相談": "AI相談",
            "ai住まいサイト": "AI住まいサイト",
            "aiサイト": "AI住まいサイト",
            "資料請求": "資料請求",
            "展示場来場予約": "展示場来場予約",
            "展示場予約": "展示場来場予約",
            "資金計画": "資金計画",
            "チャット相談": "チャット相談",
        }
        
        # 完全一致または明確なボタン押下の場合のみ
        for keyword, action in richmenu_keywords.items():
            if (keyword == text_clean or 
                f"{keyword}を開始" in text_clean or 
                f"{keyword}について" in text_clean):
                return action
        
        return "unknown"
    
    async def process_line_message(self, message_text: str, user_id: str) -> str:
        """LINE メッセージ処理（RAG統合版）"""
        start_time = time.time()
        self.performance_stats["total_messages"] += 1
        
        try:
            # 1. リッチメニューアクション検出（非常に限定的）
            richmenu_action = self.detect_richmenu_action(message_text)
            
            if richmenu_action != "unknown":
                self.performance_stats["richmenu_responses"] += 1
                logger.info(f"📱 LINE Richmenu action: {richmenu_action}")
                return self.richmenu_responses.get(richmenu_action, "ご利用ありがとうございます。")
            
            # 2. メインのRAG処理を呼び出し
            logger.info(f"🔍 LINE RAG processing: {message_text[:30]}...")
            self.performance_stats["rag_queries"] += 1
            
            # メインアプリケーションのRAG処理を呼び出し
            rag_response = await self._call_main_rag_processor(message_text, user_id)
            
            # LINE用にフォーマット調整
            line_formatted_response = self._format_for_line(rag_response)
            
            processing_time = time.time() - start_time
            logger.info(f"✅ LINE RAG response: {processing_time:.3f}s, "
                       f"source={rag_response.get('source')}, "
                       f"confidence={rag_response.get('confidence', 0):.2f}")
            
            return line_formatted_response
            
        except Exception as e:
            logger.error(f"❌ LINE message processing error: {e}")
            logger.error(traceback.format_exc())
            return self._get_error_response()
    
    async def _call_main_rag_processor(self, query: str, user_id: str) -> Dict[str, Any]:
        """メインのRAG処理を呼び出し"""
        try:
            # chat_ultra_fast.pyのSeparatedResponseGeneratorを使用
            from api.routers.chat_ultra_fast import separated_generator
            
            response = await separated_generator.generate_separated_response(
                query=query,
                platform="line",  # LINE専用プラットフォーム指定
                user=user_id
            )
            
            return response
            
        except ImportError:
            # フォールバック: main.pyのplatform_generatorを試行
            try:
                from main import platform_generator
                
                response = await platform_generator.generate_platform_response(
                    query=query,
                    platform="line",
                    user=user_id
                )
                
                return response
                
            except Exception as e:
                logger.error(f"❌ Main processor import failed: {e}")
                return {
                    "answer": "申し訳ございません。一時的にシステムの不具合が発生しています。",
                    "source": "error",
                    "confidence": 0.3
                }
            
        except Exception as e:
            logger.error(f"❌ Main RAG processor call failed: {e}")
            return {
                "answer": "申し訳ございません。一時的にシステムの不具合が発生しています。",
                "source": "error",
                "confidence": 0.3
            }
    
    def _format_for_line(self, rag_response: Dict[str, Any]) -> str:
        """RAG応答をLINE用にフォーマット"""
        answer = rag_response.get("answer", "")
        source = rag_response.get("source", "unknown")
        confidence = rag_response.get("confidence", 0.8)
        
        if not answer:
            return self._get_error_response()
        
        # 高信頼度の場合はそのまま
        if confidence >= 0.8 or source in ["rag_verified", "rag", "template", "template_enhanced"]:
            return answer
        
        # 中程度の信頼度の場合は注意書きを追加
        elif confidence >= 0.6:
            return f"{answer}\n\n※詳細については、スタッフまでお問い合わせください。"
        
        # 低信頼度の場合は安全な応答に変更
        else:
            return """ご質問ありがとうございます。

お尋ねの件について、より正確な情報をお答えするため、スタッフが直接ご対応いたします。

📞 営業時間：9:00-18:00（水曜定休）
💬 このLINEでもご相談いただけます。

お気軽にお声かけください！"""
    
    def _get_error_response(self) -> str:
        """エラー時の応答"""
        return """申し訳ございません。一時的にシステムの不具合が発生しております。

しばらくしてから再度お試しいただくか、下記までお電話でお問い合わせください。

📞 営業時間：9:00-18:00（水曜定休）

ご不便をおかけして申し訳ございません。"""

# ==============================================================================
# 安全送信関数（reply失効対策付き）
# ==============================================================================
def send_line_message_safe(reply_token: str, user_id: str, message: str) -> bool:
    """安全なLINE送信（reply失効時はPush APIにフォールバック）"""
    if not line_bot_api:
        logger.error("❌ LINE Bot API not initialized")
        return False
    
    try:
        normalized_token = normalize_line_token(LINE_CHANNEL_ACCESS_TOKEN)
        if not normalized_token:
            logger.error("❌ Failed to normalize token")
            return False
        
        configuration = Configuration(access_token=normalized_token)
        with ApiClient(configuration) as api_client:
            messaging_api = MessagingApi(api_client)
            
            # まずReply APIを試行
            try:
                messaging_api.reply_message_with_http_info(
                    ReplyMessageRequest(
                        reply_token=reply_token,
                        messages=[TextMessage(text=message)]
                    )
                )
                logger.info(f"✅ Reply message sent: {len(message)} chars")
                return True
                
            except ApiException as reply_error:
                # Reply失効時はPush APIにフォールバック
                if "Invalid reply token" in str(reply_error) or reply_error.status == 400:
                    logger.warning(f"⚠️ Reply token expired, using Push API fallback for user: {user_id}")
                    line_rag.performance_stats["push_fallbacks"] += 1
                    
                    try:
                        messaging_api.push_message_with_http_info(
                            PushMessageRequest(
                                to=user_id,
                                messages=[TextMessage(text=message)]
                            )
                        )
                        logger.info(f"✅ Push message sent as fallback: {len(message)} chars")
                        return True
                    except Exception as push_error:
                        logger.error(f"❌ Push API also failed: {push_error}")
                        return False
                else:
                    logger.error(f"❌ Reply API error: {reply_error}")
                    return False
            except Exception as general_error:
                logger.error(f"❌ Reply API general error: {general_error}")
                # 一般エラーでもPush APIフォールバックを試行
                try:
                    messaging_api.push_message_with_http_info(
                        PushMessageRequest(
                            to=user_id,
                            messages=[TextMessage(text=message)]
                        )
                    )
                    logger.info(f"✅ Push message sent as general fallback: {len(message)} chars")
                    line_rag.performance_stats["push_fallbacks"] += 1
                    return True
                except Exception as push_error:
                    logger.error(f"❌ Push API general fallback failed: {push_error}")
                    return False
        
    except Exception as e:
        logger.error(f"❌ Line message sending failed: {e}")
        return False

# グローバルインスタンス
line_rag = LineRAGIntegration()

# ==============================================================================
# Webhook エンドポイント
# ==============================================================================
@router.post("/webhook")
async def line_rag_webhook(request: Request, background_tasks: BackgroundTasks):
    """RAG統合LINEWebhook"""
    logger.info("🚀 LINE RAG Webhook called")
    
    if not line_bot_api or not handler:
        logger.error("❌ LINE Bot not configured properly")
        return {"status": "error", "message": "LINE Bot not configured"}
    
    try:
        body = await request.body()
        signature = request.headers.get("X-Line-Signature", "")
        
        if not signature:
            logger.error("❌ Missing X-Line-Signature header")
            return {"status": "error", "message": "Missing signature"}
        
        body_text = body.decode("utf-8")
        logger.info(f"📨 Webhook body preview: {body_text[:200]}...")
        
        handler.handle(body_text, signature)
        
        logger.info("✅ Webhook processed successfully")
        return {"status": "ok", "timestamp": datetime.now().isoformat()}
        
    except InvalidSignatureError as sig_error:
        logger.error(f"❌ Invalid signature: {sig_error}")
        return {"status": "signature_error"}
    except Exception as e:
        logger.error(f"💥 RAG webhook error: {e}")
        logger.error(traceback.format_exc())
        return {"status": "error", "error": str(e)}

# ==============================================================================
# イベントハンドラ（RAG統合版）
# ==============================================================================
if LINE_SDK_AVAILABLE and handler:
    
    @handler.add(FollowEvent)
    def handle_follow_rag_integrated(event):
        """フォローハンドラ（RAG統合版）"""
        start_time = time.time()
        try:
            user_id = event.source.user_id
            reply_token = event.reply_token
            
            logger.info(f"👤 New follower (RAG integrated): {user_id}")
            
            success = send_line_message_safe(reply_token, user_id, line_rag.greeting_message)
            if success:
                line_rag.performance_stats["greeting_sent"] += 1
            
            duration = (time.time() - start_time) * 1000
            logger.info(f"✅ RAG integrated greeting sent: {duration:.1f}ms, success: {success}")
            
        except Exception as e:
            logger.error(f"❌ RAG follow error: {e}")
            logger.error(traceback.format_exc())
    
    @handler.add(MessageEvent, message=TextMessageContent)
    def handle_message_rag_integrated(event):
        """メッセージハンドラ（RAG統合版）"""
        start_time = time.time()
        
        try:
            user_id = event.source.user_id
            message_text = event.message.text
            reply_token = event.reply_token
            
            logger.info(f"📱 LINE RAG processing: '{message_text[:30]}...' from user: {user_id}")
            
            # 非同期RAG処理を同期的に実行
            def process_with_rag():
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    result = loop.run_until_complete(
                        line_rag.process_line_message(message_text, user_id)
                    )
                    loop.close()
                    return result
                except Exception as e:
                    logger.error(f"RAG processing error: {e}")
                    return line_rag._get_error_response()
            
            # タイムアウト付きで実行
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(process_with_rag)
                try:
                    response_text = future.result(timeout=10)  # 10秒タイムアウト
                except concurrent.futures.TimeoutError:
                    logger.error("❌ RAG processing timeout")
                    response_text = "処理に時間がかかっています。もう一度お試しください。"
            
            # 回答送信
            success = send_line_message_safe(reply_token, user_id, response_text)
            
            duration = (time.time() - start_time) * 1000
            if success:
                logger.info(f"✅ LINE RAG response sent: {duration:.1f}ms")
            else:
                logger.error(f"❌ LINE RAG response failed after {duration:.1f}ms")
            
        except Exception as e:
            logger.error(f"❌ RAG message handler error: {e}")
            logger.error(traceback.format_exc())
            try:
                emergency = line_rag._get_error_response()
                send_line_message_safe(event.reply_token, event.source.user_id, emergency)
            except Exception as final_error:
                logger.error(f"❌ Emergency response failed: {final_error}")

    @handler.add(PostbackEvent)
    def handle_postback_rag_integrated(event):
        """Postbackハンドラ（RAG統合版）"""
        try:
            user_id = event.source.user_id
            reply_token = event.reply_token
            postback_data = event.postback.data or ""
            
            logger.info(f"🔙 Postback from {user_id}: {postback_data}")
            
            # Postbackデータの解析
            if "action=" in postback_data:
                action_value = ""
                for part in postback_data.split("&"):
                    if part.startswith("action="):
                        action_value = part.split("=", 1)[1]
                        break
                
                # アクションに対応する応答
                response_text = line_rag.richmenu_responses.get(action_value, "ご利用ありがとうございます。")
            else:
                response_text = "メニューからお選びください。"
            
            success = send_line_message_safe(reply_token, user_id, response_text)
            logger.info(f"✅ Postback processed successfully: success={success}")
            
        except Exception as e:
            logger.error(f"💥 Postback handler error: {e}")
            logger.error(traceback.format_exc())

# ==============================================================================
# 監視・デバッグエンドポイント
# ==============================================================================
@router.get("/performance")
def get_line_rag_performance():
    """LINE RAG統合パフォーマンス統計"""
    stats = line_rag.performance_stats
    
    return {
        "line_rag_integrated_stats": stats,
        "system_info": {
            "line_sdk_available": LINE_SDK_AVAILABLE,
            "line_bot_configured": line_bot_api is not None,
            "rag_integration_enabled": True,
            "reply_fallback_enabled": True,
            "push_api_enabled": True,
        },
        "features": [
            "RAG Integration with chat_ultra_fast.py",
            "Platform-separated response generation",
            "LINE-specific templates",
            "Reply Token Expiry Protection",
            "Push API Automatic Fallback",
            "LINE-Specific Response Formatting",
            "Confidence-based Response Filtering",
            "Rich Menu Action Detection"
        ],
        "timestamp": datetime.now().isoformat()
    }

@router.get("/debug")
def line_rag_debug_info():
    """LINE RAG統合デバッグ情報"""
    return {
        "line_sdk_available": LINE_SDK_AVAILABLE,
        "line_bot_api_initialized": line_bot_api is not None,
        "handler_initialized": handler is not None,
        "rag_integration": {
            "enabled": True,
            "main_processor": "chat_ultra_fast.separated_generator",
            "fallback_processor": "main.platform_generator",
            "richmenu_responses_count": len(line_rag.richmenu_responses),
            "greeting_configured": bool(line_rag.greeting_message)
        },
        "credentials_set": {
            "access_token_set": bool(LINE_CHANNEL_ACCESS_TOKEN),
            "channel_secret_set": bool(LINE_CHANNEL_SECRET)
        },
        "timestamp": datetime.now().isoformat()
    }

@router.post("/clear-cache")
def clear_line_rag_cache():
    """LINE RAG統合キャッシュクリア"""
    old_stats = line_rag.performance_stats.copy()
    
    line_rag.performance_stats = {
        "total_messages": 0,
        "richmenu_responses": 0,
        "rag_queries": 0,
        "greeting_sent": 0,
        "push_fallbacks": 0
    }
    
    return {
        "status": "line_rag_cache_cleared",
        "previous_stats": old_stats,
        "features_reset": ["performance_stats"],
        "rag_integration_maintained": True,
        "timestamp": datetime.now().isoformat()
    }

@router.get("/health")
def line_rag_health_check():
    """LINE RAG統合ヘルスチェック"""
    health_status = {
        "status": "healthy" if LINE_SDK_AVAILABLE and line_bot_api else "degraded",
        "components": {
            "line_sdk": "ok" if LINE_SDK_AVAILABLE else "error",
            "line_bot_api": "ok" if line_bot_api else "error",
            "handler": "ok" if handler else "error",
            "rag_integration": "ok",
            "credentials": "ok" if LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET else "error"
        },
        "metrics": line_rag.performance_stats,
        "timestamp": datetime.now().isoformat()
    }
    
    return health_status
