# api/routers/line_bot.py - 完全修正版（403エラー対応）

import os
import logging
import traceback
from datetime import datetime
from fastapi import APIRouter, Request, HTTPException

logger = logging.getLogger(__name__)

# LINE Bot SDK v3 imports
try:
    from linebot.v3 import WebhookHandler
    from linebot.v3.exceptions import InvalidSignatureError
    from linebot.v3.messaging import (
        Configuration,
        ApiClient,
        MessagingApi,
        ReplyMessageRequest,
        TextMessage
    )
    from linebot.v3.webhooks import (
        MessageEvent,
        TextMessageContent,
        FollowEvent
    )
    
    LINE_SDK_AVAILABLE = True
    logger.info("✅ LINE Bot SDK v3 loaded successfully")
    
except ImportError as e:
    logger.error(f"❌ LINE Bot SDK not available: {e}")
    LINE_SDK_AVAILABLE = False

# LINE Bot設定
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

# デバッグ用ログ
logger.info(f"ENV: {os.getenv('ENV')}")
logger.info(f"ACCESS_TOKEN available: {bool(LINE_CHANNEL_ACCESS_TOKEN)}")
logger.info(f"SECRET available: {bool(LINE_CHANNEL_SECRET)}")

# グローバル変数
line_bot_api = None
handler = None

def initialize_line_bot():
    """LINE Bot APIの初期化"""
    global line_bot_api, handler
    
    if not LINE_SDK_AVAILABLE:
        logger.error("❌ LINE SDK not available")
        return False
    
    if not LINE_CHANNEL_ACCESS_TOKEN:
        logger.error("❌ LINE_CHANNEL_ACCESS_TOKEN not set")
        return False
        
    if not LINE_CHANNEL_SECRET:
        logger.error("❌ LINE_CHANNEL_SECRET not set")
        return False
    
    try:
        # Configuration作成
        configuration = Configuration(
            access_token=LINE_CHANNEL_ACCESS_TOKEN
        )
        
        # Handler作成
        handler = WebhookHandler(LINE_CHANNEL_SECRET)
        
        # APIクライアント作成
        api_client = ApiClient(configuration)
        line_bot_api = MessagingApi(api_client)
        
        logger.info("✅ LINE Bot API v3 initialized successfully")
        return True
        
    except Exception as e:
        logger.error(f"❌ LINE Bot API initialization failed: {e}")
        logger.error(traceback.format_exc())
        return False

# 起動時に初期化
initialization_success = initialize_line_bot()

router = APIRouter(prefix="/line", tags=["line"])

def get_app_globals():
    """mainモジュールからグローバル変数を取得"""
    try:
        import main
        return {
            'vectorstore': getattr(main, 'vectorstore', None),
            'rag_chain_template': getattr(main, 'rag_chain_template', None),
            'llm_instance': getattr(main, 'llm_instance', None)
        }
    except Exception as e:
        logger.error(f"Failed to get app globals: {e}")
        return {'vectorstore': None, 'rag_chain_template': None, 'llm_instance': None}

def process_message_with_rag(message_text: str, user_id: str) -> str:
    """RAGを使用してメッセージを処理"""
    try:
        globals_dict = get_app_globals()
        
        if globals_dict['rag_chain_template']:
            result = globals_dict['rag_chain_template'].invoke({"query": message_text})
            return result.get("result", "申し訳ございません。回答を生成できませんでした。")
        elif globals_dict['llm_instance']:
            llm = globals_dict['llm_instance']
            prompt = f"""あなたは親切で知識豊富な住宅・建築の専門アドバイザーです。
以下の質問に対して、自然で分かりやすい日本語で回答してください。

質問: {message_text}

回答は簡潔で具体的にお願いします。"""
            
            response = llm.invoke(prompt)
            result = response.content if hasattr(response, 'content') else str(response)
            return result
        else:
            return "申し訳ございません。現在システムが準備中です。"
            
    except Exception as e:
        logger.error(f"RAG processing error: {e}")
        return "申し訳ございません。一時的にエラーが発生しました。"

def detect_richmenu_action(message_text: str) -> str:
    """リッチメニューのアクションを検出（ログに基づいた修正版）"""
    
    text = message_text.strip()
    logger.info(f"🔍 Analyzing message: '{text}'")
    
    # 完全一致チェック（ログから確認された実際のメッセージ）
    if text == "🤖 AI相談":
        logger.info("✅ Detected: AI consultation")
        return "ai_consultation"
    elif text == "🌐 AI住まいサイト":
        logger.info("✅ Detected: AI website")
        return "ai_website"
    elif text == "📋 資料請求":
        logger.info("✅ Detected: document request")
        return "document_request"
    elif text == "📍 展示場来場予約":
        logger.info("✅ Detected: showroom booking")
        return "showroom_booking"
    elif text == "💰 資金計画":
        logger.info("✅ Detected: financial planning")
        return "financial_planning"
    elif text == "💬 チャット相談":
        logger.info("✅ Detected: chat consultation")
        return "chat_consultation"
    
    # 部分一致チェック（フォールバック）
    elif "AI相談" in text or "AIとお話" in text:
        return "ai_consultation"
    elif "AI住まいサイト" in text:
        return "ai_website"
    elif "資料請求" in text:
        return "document_request"
    elif "展示場" in text or "来場" in text:
        return "showroom_booking"
    elif "資金計画" in text:
        return "financial_planning"
    elif "チャット相談" in text:
        return "chat_consultation"
    else:
        logger.info("ℹ️ No specific action detected, treating as general query")
        return "general_query"

def generate_action_response(action: str, user_id: str, original_message: str) -> str:
    """アクションに応じた応答を生成"""
    
    responses = {
        "ai_consultation": (
            "AI相談を開始します！🤖\n\n"
            "住宅に関するご質問をどうぞ！\n"
            "例：坪単価、標準仕様、ZEH住宅など"
        ),
        "ai_website": (
            "AI住まいサイトへようこそ！🏠\n\n"
            "Webサイト: https://leafy-kitsune-eb4566.netlify.app\n"
            "詳しい情報はWebサイトでご確認ください。"
        ),
        "document_request": (
            "資料請求を承ります📋\n\n"
            "以下をお送りください：\n"
            "・お名前\n"
            "・ご住所\n"
            "・電話番号"
        ),
        "showroom_booking": (
            "展示場予約を承ります📍\n\n"
            "ご希望の日時をお知らせください。\n"
            "営業時間：9:00〜18:00"
        ),
        "financial_planning": (
            "資金計画のご相談を承ります💰\n\n"
            "お名前とご連絡先をお送りください。\n"
            "専門スタッフがご対応いたします。"
        ),
        "chat_consultation": (
            "チャット相談を開始します💬\n\n"
            "ご相談内容をお送りください。\n"
            "営業時間：9:00〜18:00"
        ),
        "general_query": process_message_with_rag(original_message, user_id)
    }
    
    return responses.get(action, process_message_with_rag(original_message, user_id))

# Webhook エンドポイント
@router.post("/webhook")
async def line_webhook(request: Request):
    """LINE Webhook エンドポイント"""
    if not initialization_success:
        logger.error("LINE Bot not properly initialized")
        raise HTTPException(status_code=503, detail="LINE Bot service unavailable")
    
    body = await request.body()
    signature = request.headers.get("X-Line-Signature", "")
    
    logger.info(f"📨 Received webhook: body_size={len(body)}, signature_present={bool(signature)}")
    
    if not signature:
        logger.error("❌ Missing X-Line-Signature header")
        raise HTTPException(status_code=400, detail="Missing signature")
    
    try:
        # 署名検証を実行
        handler.handle(body.decode('utf-8'), signature)
        logger.info("✅ Webhook processed successfully")
        return {"status": "ok"}
    except InvalidSignatureError:
        logger.error("❌ Invalid signature - webhook rejected")
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        logger.error(f"❌ Webhook processing error: {e}")
        logger.error(traceback.format_exc())
        # エラーでも200を返す（LINEプラットフォーム対応）
        return {"status": "ok"}

# イベントハンドラー登録
if initialization_success and handler:
    @handler.add(MessageEvent, message=TextMessageContent)
    def handle_text_message(event):
        """テキストメッセージの処理"""
        try:
            user_id = event.source.user_id
            message_text = event.message.text.strip()
            
            logger.info(f"📨 Processing message from {user_id}: '{message_text}'")
            
            # リッチメニューアクションを検出
            action = detect_richmenu_action(message_text)
            
            # 応答メッセージを生成
            response_text = generate_action_response(action, user_id, message_text)
            
            logger.info(f"📤 Detected action: {action}")
            
            # 応答を送信（エラーハンドリング強化）
            try:
                reply_request = ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=response_text)]
                )
                
                # reply_message_with_http_info の代わりに reply_message を使用
                line_bot_api.reply_message(reply_request)
                logger.info(f"✅ Successfully sent response to {user_id}")
                
            except Exception as api_error:
                # 403エラーの詳細をログ出力
                logger.error(f"❌ Failed to send response: {api_error}")
                if hasattr(api_error, 'body'):
                    logger.error(f"Error body: {api_error.body}")
                if hasattr(api_error, 'status'):
                    logger.error(f"Error status: {api_error.status}")
                # エラーでも処理は続行
            
        except Exception as e:
            logger.error(f"❌ Error handling message: {e}")
            logger.error(traceback.format_exc())

    @handler.add(FollowEvent)
    def handle_follow(event):
        """友達追加時の処理"""
        try:
            user_id = event.source.user_id
            logger.info(f"👥 New follower: {user_id}")
            
            welcome_message = (
                "友達追加ありがとうございます！🎉\n\n"
                "下のメニューからお選びください：\n"
                "• 🤖 AI相談\n"
                "• 📋 資料請求\n"
                "• 📍 展示場予約\n"
                "• 💰 資金計画\n"
                "• 💬 チャット相談"
            )
            
            try:
                reply_request = ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=welcome_message)]
                )
                line_bot_api.reply_message(reply_request)
                logger.info(f"✅ Sent welcome message to {user_id}")
            except Exception as e:
                logger.error(f"❌ Failed to send welcome message: {e}")
            
        except Exception as e:
            logger.error(f"❌ Error handling follow event: {e}")
            logger.error(traceback.format_exc())

# ステータス確認エンドポイント
@router.get("/status")
def get_line_bot_status():
    """LINE Bot の状態確認"""
    return {
        "line_bot_configured": initialization_success,
        "line_sdk_available": LINE_SDK_AVAILABLE,
        "channel_access_token_set": bool(LINE_CHANNEL_ACCESS_TOKEN),
        "channel_secret_set": bool(LINE_CHANNEL_SECRET),
        "api_client_ready": bool(line_bot_api),
        "handler_ready": bool(handler),
        "timestamp": datetime.now().isoformat()
    }