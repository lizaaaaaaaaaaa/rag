# api/routers/line_bot.py - 修正版

import os
import logging
import traceback
from datetime import datetime
from fastapi import APIRouter, Request, HTTPException

logger = logging.getLogger(__name__)

# LINE Bot SDK v3 imports with error handling
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

# LINE Bot設定の改善
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

# デバッグ用ログ
logger.info(f"ENV: {os.getenv('ENV')}")
logger.info(f"ACCESS_TOKEN available: {bool(LINE_CHANNEL_ACCESS_TOKEN)}")
logger.info(f"SECRET available: {bool(LINE_CHANNEL_SECRET)}")
if LINE_CHANNEL_ACCESS_TOKEN:
    logger.info(f"ACCESS_TOKEN prefix: {LINE_CHANNEL_ACCESS_TOKEN[:10]}...")

# グローバル変数でAPI clientを保持
line_bot_api = None
handler = None

# LINE Bot APIの初期化（エラーハンドリング強化）
def initialize_line_bot():
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

# リッチメニューメッセージの改善された判定
def detect_richmenu_action(message_text: str) -> str:
    """リッチメニューのアクションを検出（部分一致で柔軟に対応）"""
    text = message_text.strip()
    
    # AI相談の判定（複数パターンに対応）
    if any(keyword in text for keyword in ["AI相談", "AIとお話", "🤖"]):
        return "ai_consultation"
    
    # AI住まいサイトの判定
    if any(keyword in text for keyword in ["AI住まいサイ", "住まいホーム", "🌐", "準備中"]):
        return "ai_website"
    
    # 資料請求の判定
    if any(keyword in text for keyword in ["資料請求", "📋", "送付先"]):
        return "document_request"
    
    # 展示場予約の判定
    if any(keyword in text for keyword in ["展示場", "来場", "予約", "📍"]):
        return "showroom_booking"
    
    # 資金計画の判定
    if any(keyword in text for keyword in ["資金計画", "💰", "金融相談"]):
        return "financial_planning"
    
    # チャット相談の判定
    if any(keyword in text for keyword in ["チャット相談", "💬", "スタッフ"]):
        return "chat_consultation"
    
    return "unknown"

def process_richmenu_message(action: str, user_id: str) -> str:
    """リッチメニューアクションに対する応答を生成"""
    
    if action == "ai_consultation":
        return (
            "AI相談を開始します！🤖\n\n"
            "住宅に関するご質問やお悩みを自由にご入力ください。\n"
            "例えば：\n"
            "・住宅の坪単価について教えて\n"
            "・標準仕様はどのような内容ですか？\n"
            "・ZEH住宅について知りたい\n\n"
            "どんなことでもお気軽にどうぞ！😊"
        )
    
    elif action == "ai_website":
        return (
            "AI住まいサイトは現在準備中です🏗️\n\n"
            "近日公開予定ですので、もうしばらくお待ちください。\n"
            "公開されましたらお知らせいたします！\n\n"
            "他にご質問がございましたら、お気軽にお尋ねください😊"
        )
    
    elif action == "document_request":
        return (
            "資料請求を承ります📋\n\n"
            "以下の情報をお送りください：\n"
            "1. お名前（フルネーム）\n"
            "2. 郵便番号\n"
            "3. ご住所\n"
            "4. お電話番号\n\n"
            "例：\n"
            "山田太郎\n"
            "〒123-4567\n"
            "東京都○○区○○1-2-3\n"
            "090-1234-5678"
        )
    
    elif action == "showroom_booking":
        return (
            "展示場のご予約を承ります📍\n\n"
            "ご希望の日時をお知らせください。\n"
            "営業時間：9:00〜18:00\n\n"
            "例：\n"
            "「2月15日（木）14時に予約したいです」\n\n"
            "※土日は混雑することがございます。\n"
            "平日のご来場がおすすめです😊"
        )
    
    elif action == "financial_planning":
        return (
            "資金計画のご相談を承ります💰\n\n"
            "まず、以下の情報をお送りください：\n"
            "1. お名前\n"
            "2. ご連絡先（電話番号）\n"
            "3. ご希望の相談方法\n"
            "   - オンライン相談\n"
            "   - 来店相談\n"
            "   - 電話相談\n\n"
            "専門スタッフが丁寧にご対応いたします！"
        )
    
    elif action == "chat_consultation":
        return (
            "チャット相談を開始します💬\n\n"
            "スタッフが対応いたします。\n"
            "お気軽にご相談内容をお送りください！\n\n"
            "営業時間：9:00〜18:00\n"
            "※営業時間外のメッセージは翌営業日に返信いたします。"
        )
    
    else:
        return (
            "メッセージを受信いたしました。\n\n"
            "下のメニューから選択していただくか、\n"
            "直接ご質問をお送りください😊"
        )

# Webhook エンドポイント
@router.post("/webhook")
async def line_webhook(request: Request):
    """LINE Webhook エンドポイント"""
    if not initialization_success:
        logger.error("LINE Bot not properly initialized")
        raise HTTPException(status_code=503, detail="LINE Bot service unavailable")
    
    body = await request.body()
    signature = request.headers.get("X-Line-Signature", "")
    
    logger.info(f"Received webhook: body_size={len(body)}")
    
    try:
        handler.handle(body.decode('utf-8'), signature)
        return {"status": "ok"}
    except InvalidSignatureError:
        logger.error("Invalid signature")
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="Internal server error")

# イベントハンドラー登録
if initialization_success and handler:
    @handler.add(MessageEvent, message=TextMessageContent)
    def handle_text_message(event):
        """テキストメッセージの処理"""
        try:
            user_id = event.source.user_id
            message_text = event.message.text.strip()
            
            logger.info(f"📨 Received message from {user_id}: '{message_text}'")
            
            # リッチメニューアクションを検出
            action = detect_richmenu_action(message_text)
            logger.info(f"🔍 Detected action: {action}")
            
            if action == "ai_consultation":
                # AI相談の場合は直接RAG処理を開始
                response_text = process_richmenu_message(action, user_id)
            elif action != "unknown":
                # その他のリッチメニューアクション
                response_text = process_richmenu_message(action, user_id)
            else:
                # 通常のAI回答（RAGチェーン使用）
                try:
                    globals_dict = get_app_globals()
                    if globals_dict['rag_chain_template']:
                        result = globals_dict['rag_chain_template'].invoke({"query": message_text})
                        response_text = result.get("result", "申し訳ございません。回答を生成できませんでした。")
                    else:
                        response_text = "申し訳ございません。システムが準備中です。"
                except Exception as rag_error:
                    logger.error(f"RAG processing error: {rag_error}")
                    response_text = "申し訳ございません。一時的にエラーが発生しました。"
            
            # 応答を送信
            try:
                line_bot_api.reply_message_with_http_info(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=response_text)]
                    )
                )
                logger.info(f"✅ Successfully sent response to {user_id}")
            except Exception as api_error:
                logger.error(f"❌ Failed to send response: {api_error}")
            
        except Exception as e:
            logger.error(f"❌ Error handling message: {e}")
            logger.error(traceback.format_exc())

    @handler.add(FollowEvent)
    def handle_follow(event):
        """友達追加時の処理"""
        try:
            user_id = event.source.user_id
            logger.info(f"New follower: {user_id}")
            
            welcome_message = (
                "友達追加ありがとうございます！🎉\n\n"
                "キノエデザインホームです。\n"
                "家づくりに関するご相談を承っております。\n\n"
                "下のメニューから、お好きな項目をお選びください：\n"
                "• AI相談 - AIが質問に即座に回答\n"
                "• 資料請求 - パンフレットをお送りします\n"
                "• 展示場予約 - 実際の家を見学\n"
                "• 資金計画 - お金の相談\n"
                "• チャット相談 - スタッフと直接相談\n\n"
                "お気軽にご利用ください！"
            )
            
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=welcome_message)]
                )
            )
            logger.info(f"✅ Sent welcome message to {user_id}")
            
        except Exception as e:
            logger.error(f"❌ Error handling follow event: {e}")

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