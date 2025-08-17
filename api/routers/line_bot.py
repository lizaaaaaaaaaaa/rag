# line_bot.py - 修正されたLINE Bot実装

import logging
import os
import re
import json
import asyncio
import traceback
from datetime import datetime
from typing import Dict, Optional, Any

from fastapi import APIRouter, Request, BackgroundTasks
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# LINE Bot SDK v3
try:
    from linebot.v3 import WebhookHandler
    from linebot.v3.exceptions import InvalidSignatureError
    from linebot.v3.messaging import (
        Configuration, ApiClient, MessagingApi, ReplyMessageRequest, TextMessage,
    )
    from linebot.v3.webhooks import MessageEvent, TextMessageContent, PostbackEvent
    LINE_SDK_AVAILABLE = True
    logger.info("✅ LINE Bot SDK v3 imported successfully")
except ImportError as e:
    logger.error(f"❌ LINE Bot SDK not available: {e}")
    LINE_SDK_AVAILABLE = False
    
    # ダミークラス
    class WebhookHandler:
        def __init__(self, *args, **kwargs): pass
        def add(self, *args, **kwargs): 
            def decorator(func): return func
            return decorator
        def handle(self, *args, **kwargs): pass

router = APIRouter(prefix="/line", tags=["line"])

def get_line_credentials():
    """LINE認証情報を安全に取得"""
    access_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    channel_secret = os.getenv("LINE_CHANNEL_SECRET")
    
    logger.info("Getting LINE credentials...")
    logger.info(f"Access token type: {type(access_token)}")
    logger.info(f"Channel secret type: {type(channel_secret)}")
    
    return access_token, channel_secret

def normalize_line_token_fixed(token: Any) -> str:
    """修正されたLINEトークン正規化関数"""
    if token is None:
        logger.error("Token is None")
        return ""
    
    # bytes オブジェクトの処理
    if isinstance(token, bytes):
        try:
            token = token.decode("utf-8")
            logger.info("Successfully decoded token from bytes")
        except UnicodeDecodeError as e:
            logger.error(f"Failed to decode token from bytes: {e}")
            return ""
    
    # 文字列に変換
    token_str = str(token).strip()
    
    # デバッグ情報
    logger.info(f"Original token length: {len(token_str)}")
    logger.info(f"Token starts with: {token_str[:20]}...")
    
    # 不要なプレフィックスを削除
    if token_str.startswith("Bearer "):
        token_str = token_str[7:].strip()
        logger.info("Removed 'Bearer ' prefix")
    
    # Python のbytes表現を削除
    if token_str.startswith("b'") and token_str.endswith("'"):
        token_str = token_str[2:-1]
        logger.info("Removed Python bytes notation")
    
    # 追加のクリーンアップ
    token_str = token_str.replace('"', '').replace("'", "")
    
    # 空白文字を削除
    if any(char in token_str for char in ['\n', '\r', '\t', ' ']):
        logger.warning("Token contains whitespace, cleaning...")
        token_str = ''.join(token_str.split())
    
    # 最終検証
    if not token_str:
        logger.error("Token is empty after normalization")
        return ""
    
    if len(token_str) < 50:
        logger.warning(f"Token might be too short: {len(token_str)} characters")
    
    logger.info(f"Normalized token length: {len(token_str)}")
    return token_str

# LINE Bot初期化（修正版）
LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET = get_line_credentials()

line_bot_api = None
handler = None

if LINE_SDK_AVAILABLE:
    if LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET:
        try:
            # トークンを正規化
            normalized_token = normalize_line_token_fixed(LINE_CHANNEL_ACCESS_TOKEN)
            normalized_secret = normalize_line_token_fixed(LINE_CHANNEL_SECRET)
            
            if not normalized_token:
                raise ValueError("Normalized access token is empty")
            if not normalized_secret:
                raise ValueError("Normalized channel secret is empty")
            
            # Configuration作成
            configuration = Configuration(access_token=normalized_token)
            
            # WebhookHandler作成
            handler = WebhookHandler(normalized_secret)
            
            # MessagingApi作成
            with ApiClient(configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
            
            logger.info("✅ LINE Bot API v3 initialized successfully with normalized tokens")
            
        except Exception as e:
            logger.error(f"❌ LINE Bot API initialization failed: {e}")
            logger.error(traceback.format_exc())
            line_bot_api, handler = None, None
    else:
        logger.warning("⚠️ LINE Bot credentials not found")
        line_bot_api, handler = None, None
else:
    logger.warning("⚠️ LINE Bot SDK not available")

# リッチメニュー応答定義（画像に基づく）
RICHMENU_RESPONSES = {
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

📱 アクセス方法：
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

3営業日以内にお送いたします！""",

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

def detect_richmenu_action(message_text: str) -> str:
    """リッチメニューアクションを検出"""
    text_clean = message_text.lower().replace(" ", "").replace("　", "")
    
    # 完全一致を優先
    richmenu_keywords = {
        "ai相談": "AI相談",
        "ai住まいサイト": "AI住まいサイト", 
        "aiサイト": "AI住まいサイト",
        "資料請求": "資料請求",
        "展示場来場予約": "展示場来場予約",
        "展示場予約": "展示場来場予約",
        "展示場": "展示場来場予約",
        "資金計画": "資金計画",
        "チャット相談": "チャット相談",
        "チャット": "チャット相談"
    }
    
    for keyword, action in richmenu_keywords.items():
        if keyword in text_clean:
            return action
    
    return "unknown"

def send_line_reply_safe(reply_token: str, message_text: str) -> bool:
    """安全なLINE返信送信"""
    if not line_bot_api:
        logger.error("LINE Bot API not initialized")
        return False
    
    try:
        # トークンの再正規化
        normalized_token = normalize_line_token_fixed(LINE_CHANNEL_ACCESS_TOKEN)
        if not normalized_token:
            logger.error("Failed to normalize access token for reply")
            return False
        
        # 新しいConfiguration作成
        configuration = Configuration(access_token=normalized_token)
        
        with ApiClient(configuration) as api_client:
            messaging_api = MessagingApi(api_client)
            
            # メッセージ送信
            messaging_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=reply_token,
                    messages=[TextMessage(text=message_text)]
                )
            )
        
        logger.info(f"✅ Reply sent successfully (length: {len(message_text)})")
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to send LINE reply: {e}")
        logger.error(traceback.format_exc())
        return False

# Webhook エンドポイント
@router.post("/webhook")
async def line_webhook_fixed(request: Request, background_tasks: BackgroundTasks):
    """修正されたLINE Webhook"""
    logger.info("🚀 LINE Webhook called")
    
    if not line_bot_api or not handler:
        logger.error("❌ LINE Bot not configured properly")
        return {"status": "error", "message": "LINE Bot not configured"}
    
    try:
        body = await request.body()
        signature = request.headers.get("X-Line-Signature", "")
        
        logger.info(f"📨 Webhook - Body length: {len(body)}, Has signature: {'Yes' if signature else 'No'}")
        
        if not signature:
            logger.error("❌ Missing X-Line-Signature header")
            return {"status": "error", "message": "Missing signature"}
        
        try:
            body_text = body.decode("utf-8")
            logger.info(f"📄 Body preview: {body_text[:200]}...")
            
            # イベント処理
            handler.handle(body_text, signature)
            
            logger.info("✅ Webhook processed successfully")
            return {"status": "ok", "timestamp": datetime.now().isoformat()}
            
        except InvalidSignatureError as sig_error:
            logger.error(f"❌ Invalid signature: {sig_error}")
            return {"status": "signature_error", "timestamp": datetime.now().isoformat()}
            
    except Exception as e:
        logger.error(f"💥 Webhook error: {e}")
        logger.error(traceback.format_exc())
        return {"status": "error", "error": str(e), "timestamp": datetime.now().isoformat()}

# イベントハンドラ（修正版）
if LINE_SDK_AVAILABLE and handler:
    
    @handler.add(MessageEvent, message=TextMessageContent)
    def handle_text_message_fixed(event):
        """修正されたメッセージハンドラ"""
        start_time = datetime.now()
        
        try:
            user_id = event.source.user_id
            message_text = event.message.text
            reply_token = event.reply_token
            
            logger.info(f"📱 Message from {user_id}: '{message_text}'")
            
            # リッチメニューアクション検出
            action = detect_richmenu_action(message_text)
            
            if action != "unknown":
                logger.info(f"🎯 Richmenu action detected: {action}")
                response_text = RICHMENU_RESPONSES.get(action, RICHMENU_RESPONSES.get("unknown", "申し訳ございません。"))
            else:
                logger.info("💬 General message processing")
                # 一般的な質問処理
                response_text = process_general_question(message_text)
            
            # 返信送信
            success = send_line_reply_safe(reply_token, response_text)
            
            duration = (datetime.now() - start_time).total_seconds()
            logger.info(f"✅ Message processed: success={success}, time={duration:.3f}s")
            
        except Exception as e:
            logger.error(f"💥 Message handler error: {e}")
            logger.error(traceback.format_exc())
            
            # 緊急時の応答
            try:
                emergency_text = "申し訳ございません。一時的にエラーが発生しました。しばらくしてから再度お試しください。"
                send_line_reply_safe(event.reply_token, emergency_text)
            except Exception as final_error:
                logger.error(f"💥 Emergency response failed: {final_error}")
    
    @handler.add(PostbackEvent)
    def handle_postback_fixed(event):
        """修正されたPostbackハンドラ"""
        try:
            user_id = event.source.user_id
            postback_data = event.postback.data or ""
            
            logger.info(f"🔙 Postback from {user_id}: {postback_data}")
            
            # Postbackデータの解析
            if "action=" in postback_data:
                action_value = ""
                for part in postback_data.split("&"):
                    if part.startswith("action="):
                        action_value = part.split("=", 1)[1]
                        break
                
                response_text = RICHMENU_RESPONSES.get(action_value, "ご利用ありがとうございます。")
            else:
                response_text = "メニューからお選びください。"
            
            send_line_reply_safe(event.reply_token, response_text)
            logger.info("✅ Postback processed successfully")
            
        except Exception as e:
            logger.error(f"💥 Postback handler error: {e}")

def process_general_question(message_text: str) -> str:
    """一般的な質問の処理"""
    try:
        # RAGシステムとの連携
        globals_dict = get_app_globals()
        if globals_dict.get('rag_chain_template'):
            result = globals_dict['rag_chain_template'].invoke({"query": message_text})
            return result.get("result", "申し訳ございません。お答えできませんでした。")
        else:
            return "ご質問ありがとうございます。詳しくはお問い合わせください。"
            
    except Exception as e:
        logger.error(f"Error processing general question: {e}")
        return "申し訳ございません。エラーが発生しました。"

def get_app_globals():
    """アプリのグローバル変数を取得"""
    try:
        import main
        return {
            'vectorstore': getattr(main, 'vectorstore', None),
            'rag_chain_template': getattr(main, 'rag_chain_template', None),
            'llm_instance': getattr(main, 'llm_instance', None)
        }
    except Exception as e:
        logger.error(f"Failed to get app globals: {e}")
        return {}

# デバッグエンドポイント
@router.get("/debug")
def line_debug_info():
    """LINE Bot デバッグ情報"""
    return {
        "line_sdk_available": LINE_SDK_AVAILABLE,
        "line_bot_api_initialized": line_bot_api is not None,
        "handler_initialized": handler is not None,
        "credentials_set": {
            "access_token_set": bool(LINE_CHANNEL_ACCESS_TOKEN),
            "channel_secret_set": bool(LINE_CHANNEL_SECRET)
        },
        "normalized_token_length": len(normalize_line_token_fixed(LINE_CHANNEL_ACCESS_TOKEN)) if LINE_CHANNEL_ACCESS_TOKEN else 0,
        "timestamp": datetime.now().isoformat()
    }

@router.get("/test-credentials")
def test_line_credentials():
    """LINE認証情報テスト"""
    access_token, channel_secret = get_line_credentials()
    
    return {
        "original_token_type": str(type(access_token)),
        "original_secret_type": str(type(channel_secret)),
        "normalized_token_length": len(normalize_line_token_fixed(access_token)) if access_token else 0,
        "normalized_secret_length": len(normalize_line_token_fixed(channel_secret)) if channel_secret else 0,
        "token_preview": normalize_line_token_fixed(access_token)[:10] + "..." if access_token else "None",
        "timestamp": datetime.now().isoformat()
    }