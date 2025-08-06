# api/routers/line_bot.py - 完全修正版（リッチメニュー対応）

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
    """リッチメニューのアクションを検出（実際のメッセージに対応）"""
    
    text = message_text.strip()
    logger.info(f"🔍 Analyzing message: '{text}'")
    logger.info(f"📏 Message length: {len(text)}")
    logger.info(f"🔤 Message bytes: {text.encode('utf-8')}")
    
    # 実際のリッチメニューメッセージに対応した判定
    # 部分一致で判定（より柔軟性を持たせる）
    
    # AI相談の判定（複数パターンに対応）
    if any(pattern in text for pattern in [
        "AIとお話", "AI相談", "💬", "🤖", "テスト・", "AIと話"
    ]):
        logger.info("✅ Detected: AI consultation")
        return "ai_consultation"
    
    # AI住まいサイトの判定
    elif any(pattern in text for pattern in [
        "AI住まいサイト", "🏢", "住まいホームページ", "準備中", "😴"
    ]):
        logger.info("✅ Detected: AI website")
        return "ai_website"
    
    # 資料請求の判定
    elif any(pattern in text for pattern in [
        "資料請求", "📋", "をご入力ください", "😊", "おるも和歌付き"
    ]):
        logger.info("✅ Detected: document request")
        return "document_request"
    
    # 展示場来場予約の判定
    elif any(pattern in text for pattern in [
        "展示場来場", "📍", "予約手続き", "メッセージください"
    ]):
        logger.info("✅ Detected: showroom booking")
        return "showroom_booking"
    
    # 資金計画の判定
    elif any(pattern in text for pattern in [
        "資金計画", "💰", "AI金融相談", "年収", "自己資金", "調査"
    ]):
        logger.info("✅ Detected: financial planning")
        return "financial_planning"
    
    # チャット相談の判定
    elif any(pattern in text for pattern in [
        "チャット相談", "💬", "スタッフと", "気転に", "営業時間"
    ]):
        logger.info("✅ Detected: chat consultation")
        return "chat_consultation"
    
    # どのパターンにも該当しない場合
    else:
        logger.info(f"ℹ️ No specific action detected for: '{text}', treating as general query")
        return "general_query"

def generate_action_response(action: str, user_id: str, original_message: str) -> str:
    """アクションに応じた応答を生成"""
    
    logger.info(f"📤 Generating response for action: {action}")
    
    responses = {
        "ai_consultation": (
            "AI相談を開始します！🤖\n\n"
            "住宅に関するご質問をどうぞ！\n"
            "例：坪単価、標準仕様、ZEH住宅など\n\n"
            "何でもお気軽にご質問ください✨"
        ),
        "ai_website": (
            "AI住まいサイトへようこそ！🏠\n\n"
            "現在準備中です。今しばらくお待ちください😴\n\n"
            "詳しい情報は以下でご確認いただけます：\n"
            "https://leafy-kitsune-eb4566.netlify.app"
        ),
        "document_request": (
            "資料請求を承ります📋\n\n"
            "以下の情報をお送りください：\n"
            "・お名前\n"
            "・ご住所\n"
            "・電話番号\n"
            "・ご希望の資料（カタログ・プラン集など）"
        ),
        "showroom_booking": (
            "展示場予約を承ります📍\n\n"
            "ご希望の日時をお知らせください：\n"
            "・第1希望日時\n"
            "・第2希望日時\n"
            "・お名前\n"
            "・電話番号\n\n"
            "営業時間：9:00〜18:00"
        ),
        "financial_planning": (
            "資金計画のご相談を承ります💰\n\n"
            "以下の情報をお教えください：\n"
            "・年収\n"
            "・自己資金\n"
            "・ご希望の建築エリア\n"
            "・ご家族構成\n\n"
            "専門スタッフがご対応いたします✨"
        ),
        "chat_consultation": (
            "チャット相談を開始します💬\n\n"
            "ご相談内容をお送りください。\n"
            "スタッフが丁寧にお答えいたします。\n\n"
            "営業時間：9:00〜18:00"
        ),
        "general_query": process_message_with_rag(original_message, user_id)
    }
    
    response = responses.get(action, process_message_with_rag(original_message, user_id))
    logger.info(f"✅ Generated response for {action}: {len(response)} characters")
    return response

# Webhook エンドポイント
@router.post("/webhook")
async def line_webhook(request: Request):
    """LINE Webhook エンドポイント（修正版）"""
    if not initialization_success:
        logger.error("❌ LINE Bot not properly initialized")
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
        """テキストメッセージの処理（修正版）"""
        try:
            user_id = event.source.user_id
            message_text = event.message.text.strip()
            
            logger.info(f"📨 Processing message from {user_id}")
            logger.info(f"📝 Message content: '{message_text}'")
            logger.info(f"📏 Message length: {len(message_text)}")
            
            # リッチメニューアクションを検出
            action = detect_richmenu_action(message_text)
            
            # 応答メッセージを生成
            response_text = generate_action_response(action, user_id, message_text)
            
            logger.info(f"🎯 Detected action: {action}")
            logger.info(f"📤 Response length: {len(response_text)}")
            
            # 応答を送信
            try:
                reply_request = ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=response_text)]
                )
                
                line_bot_api.reply_message(reply_request)
                logger.info(f"✅ Successfully sent response to {user_id} for action: {action}")
                
            except Exception as api_error:
                logger.error(f"❌ Failed to send response: {api_error}")
                if hasattr(api_error, 'body'):
                    logger.error(f"Error body: {api_error.body}")
                if hasattr(api_error, 'status'):
                    logger.error(f"Error status: {api_error.status}")
            
        except Exception as e:
            logger.error(f"❌ Error handling message: {e}")
            logger.error(traceback.format_exc())

    @handler.add(FollowEvent)
    def handle_follow(event):
        """友達追加時の処理（修正版）"""
        try:
            user_id = event.source.user_id
            logger.info(f"👥 New follower: {user_id}")
            
            welcome_message = (
                "友達追加ありがとうございます！🎉\n\n"
                "キノエデザインホームの公式LINEへようこそ✨\n\n"
                "下のメニューからお選びください：\n"
                "🤖 AI相談 - 住宅に関する質問にAIがお答え\n"
                "🏢 AI住まいサイト - ホームページをご覧\n"
                "📋 資料請求 - カタログ等の資料をお送り\n"
                "📍 展示場予約 - 展示場見学のご予約\n"
                "💰 資金計画 - 住宅ローン等のご相談\n"
                "💬 チャット相談 - スタッフとの直接相談\n\n"
                "お気軽にお使いください！"
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
        "timestamp": datetime.now().isoformat(),
        "debug_info": {
            "env": os.getenv("ENV"),
            "access_token_prefix": LINE_CHANNEL_ACCESS_TOKEN[:10] + "..." if LINE_CHANNEL_ACCESS_TOKEN else "None",
            "secret_prefix": LINE_CHANNEL_SECRET[:10] + "..." if LINE_CHANNEL_SECRET else "None"
        }
    }

# デバッグエンドポイント
@router.get("/debug/richmenu")
def debug_richmenu():
    """リッチメニューデバッグ情報"""
    return {
        "expected_messages": [
            "A：テスト・ 💬AIとお話",
            "B：テスト・ 🏢AI住まいサイト AI住まいホームページ。準備中です 今しばらくお待ちください😴",
            "C：テスト・ 📋資料請求します！ おるも和歌付き をご入力ください😊",
            "D：テスト・ 📍展示場来場 予約手続き を メッセージください",
            "E：テスト・ 💰資金計画 AI金融相談スタート！ 年収・自己資金など 調査にお間にします😊",
            "F：チャット相談 スタッフとチャット相談 気転にメッセージどうぞ！ 営業時間9-18時"
        ],
        "detection_keywords": {
            "ai_consultation": ["AIとお話", "AI相談", "💬", "🤖"],
            "ai_website": ["AI住まいサイト", "🏢", "住まいホームページ"],
            "document_request": ["資料請求", "📋", "をご入力ください"],
            "showroom_booking": ["展示場来場", "📍", "予約手続き"],
            "financial_planning": ["資金計画", "💰", "AI金融相談"],
            "chat_consultation": ["チャット相談", "💬", "スタッフと"]
        }
    }