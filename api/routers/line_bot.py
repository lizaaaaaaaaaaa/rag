# api/routers/line_bot.py - 修正版（リッチメニュー完全対応）

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

# グローバル変数でAPI clientを保持
line_bot_api = None
handler = None

def initialize_line_bot():
    """LINE Bot APIの初期化（エラーハンドリング強化版）"""
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
        
        # LLMが利用可能な場合は直接使用
        if globals_dict['llm_instance']:
            llm = globals_dict['llm_instance']
            prompt = f"""あなたは親切で知識豊富な住宅・建築の専門アドバイザーです。
以下の質問に対して、自然で分かりやすい日本語で回答してください。

質問: {message_text}

回答は簡潔で具体的にお願いします。"""
            
            response = llm.invoke(prompt)
            result = response.content if hasattr(response, 'content') else str(response)
            return result
            
        # RAGチェーンが利用可能な場合
        elif globals_dict['rag_chain_template']:
            result = globals_dict['rag_chain_template'].invoke({"query": message_text})
            return result.get("result", "申し訳ございません。回答を生成できませんでした。")
        
        # どちらも利用できない場合
        else:
            return "申し訳ございません。現在システムが準備中です。しばらくしてから再度お試しください。"
            
    except Exception as e:
        logger.error(f"RAG processing error: {e}")
        return "申し訳ございません。一時的にエラーが発生しました。しばらくしてから再度お試しください。"

def detect_and_process_message(message_text: str, user_id: str) -> str:
    """メッセージを検出して適切な応答を返す（完全版）"""
    
    text = message_text.strip()
    logger.info(f"🔍 Received message from {user_id}: '{text}'")
    
    # まず完全一致を試みる（リッチメニューからの定型メッセージ）
    exact_responses = {
        "AI相談": "ai_consultation",
        "AI住まいサイト": "ai_website",
        "資料請求": "document_request",
        "展示場来場予約": "showroom_booking",
        "資金計画": "financial_planning",
        "チャット相談": "chat_consultation"
    }
    
    # 完全一致チェック
    for key, action in exact_responses.items():
        if text == key:
            logger.info(f"✅ Exact match detected: {action}")
            return generate_action_response(action, user_id, text)
    
    # 部分一致チェック（リッチメニューのテキストが複雑な場合）
    # AI相談関連
    if any(keyword in text for keyword in ["AI相談", "AIとお話", "AI相談を開始", "🤖"]):
        logger.info("✅ Detected: AI consultation request")
        return generate_action_response("ai_consultation", user_id, text)
    
    # AI住まいサイト関連
    elif any(keyword in text for keyword in ["AI住まいサイト", "AIまよいサイト", "住まいホーム", "🌐"]):
        logger.info("✅ Detected: AI website")
        return generate_action_response("ai_website", user_id, text)
    
    # 資料請求関連
    elif any(keyword in text for keyword in ["資料請求", "📋", "送付先"]):
        logger.info("✅ Detected: document request")
        return generate_action_response("document_request", user_id, text)
    
    # 展示場予約関連
    elif any(keyword in text for keyword in ["展示場", "来場", "予約", "📍"]):
        logger.info("✅ Detected: showroom booking")
        return generate_action_response("showroom_booking", user_id, text)
    
    # 資金計画関連
    elif any(keyword in text for keyword in ["資金計画", "💰", "金融相談"]):
        logger.info("✅ Detected: financial planning")
        return generate_action_response("financial_planning", user_id, text)
    
    # チャット相談関連
    elif any(keyword in text for keyword in ["チャット相談", "💬", "スタッフ"]):
        logger.info("✅ Detected: chat consultation")
        return generate_action_response("chat_consultation", user_id, text)
    
    # どれにも該当しない場合は通常のAI回答として処理
    else:
        logger.info("ℹ️ Processing as general AI query")
        return process_message_with_rag(text, user_id)

def generate_action_response(action: str, user_id: str, original_message: str) -> str:
    """アクションに応じた応答を生成"""
    
    responses = {
        "ai_consultation": (
            "AI相談を開始します！🤖\n\n"
            "住宅に関するご質問やお悩みを自由にご入力ください。\n"
            "例えば：\n"
            "・住宅の坪単価について教えて\n"
            "・標準仕様はどのような内容ですか？\n"
            "・ZEH住宅について知りたい\n\n"
            "どんなことでもお気軽にどうぞ！😊"
        ),
        "ai_website": (
            "AI住まいサイトは現在準備中です🏗️\n\n"
            "近日公開予定ですので、もうしばらくお待ちください。\n"
            "公開されましたらお知らせいたします！\n\n"
            "他にご質問がございましたら、お気軽にお尋ねください😊"
        ),
        "document_request": (
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
        ),
        "showroom_booking": (
            "展示場のご予約を承ります📍\n\n"
            "ご希望の日時をお知らせください。\n"
            "営業時間：9:00〜18:00\n\n"
            "例：\n"
            "「2月15日（木）14時に予約したいです」\n\n"
            "※土日は混雑することがございます。\n"
            "平日のご来場がおすすめです😊"
        ),
        "financial_planning": (
            "資金計画のご相談を承ります💰\n\n"
            "まず、以下の情報をお送りください：\n"
            "1. お名前\n"
            "2. ご連絡先（電話番号）\n"
            "3. ご希望の相談方法\n"
            "   - オンライン相談\n"
            "   - 来店相談\n"
            "   - 電話相談\n\n"
            "専門スタッフが丁寧にご対応いたします！"
        ),
        "chat_consultation": (
            "チャット相談を開始します💬\n\n"
            "スタッフが対応いたします。\n"
            "お気軽にご相談内容をお送りください！\n\n"
            "営業時間：9:00〜18:00\n"
            "※営業時間外のメッセージは翌営業日に返信いたします。"
        )
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
    
    # 受信したメッセージの内容をログ出力（デバッグ用）
    try:
        import json
        body_json = json.loads(body)
        if 'events' in body_json:
            for event in body_json['events']:
                if event.get('type') == 'message' and event.get('message', {}).get('type') == 'text':
                    logger.info(f"📨 Webhook received text: '{event['message']['text']}'")
    except:
        pass
    
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
        raise HTTPException(status_code=500, detail="Internal server error")

# イベントハンドラー登録
if initialization_success and handler:
    @handler.add(MessageEvent, message=TextMessageContent)
    def handle_text_message(event):
        """テキストメッセージの処理"""
        try:
            user_id = event.source.user_id
            message_text = event.message.text.strip()
            
            logger.info(f"📨 Processing message from {user_id}: '{message_text}'")
            
            # メッセージを検出して処理
            response_text = detect_and_process_message(message_text, user_id)
            
            logger.info(f"📤 Sending response ({len(response_text)} chars)")
            
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
                logger.error(traceback.format_exc())
            
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