# api/routers/line_bot.py - 修正版（リッチメニュー完全対応）

import os
import logging
import traceback
import asyncio
from datetime import datetime
from fastapi import APIRouter, Request, HTTPException

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
    logger = logging.getLogger(__name__)
    logger.info("✅ LINE Bot SDK v3.5.0 loaded successfully")
   
except ImportError as e:
    logging.getLogger(__name__).error(f"LINE Bot SDK not available: {e}")
    LINE_SDK_AVAILABLE = False
   
    # Dummy classes for development
    class WebhookHandler:
        def __init__(self, *args, **kwargs): pass
        def add(self, *args, **kwargs):
            def decorator(func): return func
            return decorator
        def handle(self, *args, **kwargs): pass
    class MessagingApi:
        def __init__(self, *args, **kwargs): pass
    class TextMessage:
        def __init__(self, *args, **kwargs): pass

logger = logging.getLogger(__name__)

# LINE Bot設定
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

# LINE Bot APIの初期化
if LINE_SDK_AVAILABLE and LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET:
    try:
        configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
        handler = WebhookHandler(LINE_CHANNEL_SECRET)
       
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
       
        logger.info("✅ LINE Bot API v3 initialized successfully")
    except Exception as e:
        logger.error(f"❌ LINE Bot API initialization failed: {e}")
        line_bot_api = None
        handler = None
else:
    line_bot_api = None
    handler = None
    if LINE_SDK_AVAILABLE:
        logger.warning("⚠️ LINE Bot credentials not found")
    else:
        logger.warning("⚠️ LINE Bot SDK not available")

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

# api/routers/line_bot.py の修正部分

def detect_richmenu_action(message_text: str) -> str:
    """リッチメニューのアクションを検出（シンプル版）"""
    
    logger.info(f"Detecting rich menu action for message: {message_text}")
    
    # 完全一致でチェック（最も確実）
    action_map = {
        "AI相談を開始": "ai_consultation",
        "AI住まいサイト": "ai_site",
        "資料請求": "document_request",
        "展示場予約": "exhibition_reservation",
        "資金計画相談": "finance_planning",
        "チャット相談": "chat_consultation"
    }
    
    # 完全一致チェック
    if message_text in action_map:
        action = action_map[message_text]
        logger.info(f"Detected action (exact match): {action}")
        return action
    
    # 部分一致チェック（フォールバック）
    for key, value in action_map.items():
        if key in message_text:
            logger.info(f"Detected action (partial match): {value}")
            return value
    
    # どのパターンにも一致しない場合は一般的な質問として処理
    logger.info("No rich menu pattern detected, treating as general message")
    return "general"

def get_richmenu_response(action: str, user_id: str) -> str:
    """リッチメニューアクションに対する応答を生成（改善版）"""
    
    responses = {
        "ai_consultation": (
            "🤖 AI相談を開始します！\n\n"
            "キノエデザインの住まいAIコンシェルジュです。\n"
            "住まいに関するご質問をなんでもお聞きください。\n\n"
            "例えば...\n"
            "・坪単価について教えて\n"
            "・標準仕様について知りたい\n"
            "・耐震性能は？\n"
            "・断熱性能について\n\n"
            "お気軽にご質問ください😊"
        ),
        "ai_site": (
            "🏠 AI住まいサイト\n\n"
            "キノエデザインのAI住まいサイトへようこそ！\n\n"
            "現在準備中です。\n"
            "もうしばらくお待ちください。\n\n"
            "完成次第、お知らせいたします📢"
        ),
        "document_request": (
            "📋 資料請求承ります\n\n"
            "キノエデザインの資料をお送りいたします。\n\n"
            "以下の情報をメッセージでお送りください：\n"
            "1️⃣ お名前（フルネーム）\n"
            "2️⃣ ご住所（郵便番号から）\n"
            "3️⃣ お電話番号\n"
            "4️⃣ ご希望の資料\n"
            "  ・総合カタログ\n"
            "  ・実例集\n"
            "  ・価格表\n\n"
            "お待ちしております📮"
        ),
        "exhibition_reservation": (
            "📍 展示場来場予約\n\n"
            "キノエデザイン展示場へのご来場予約を承ります。\n\n"
            "【営業時間】\n"
            "平日・土日祝：9:00〜18:00\n"
            "定休日：水曜日\n\n"
            "【展示場住所】\n"
            "〒XXX-XXXX\n"
            "住所をここに記載\n\n"
            "ご希望の日時をメッセージでお送りください。\n"
            "例）1月20日（土）14:00\n\n"
            "スタッフ一同、お待ちしております🏠"
        ),
        "finance_planning": (
            "💰 資金計画相談\n\n"
            "マイホームの資金計画をサポートいたします。\n\n"
            "住宅ローンシミュレーション、返済計画など\n"
            "お客様に最適なプランをご提案します。\n\n"
            "ご相談内容をメッセージでお送りください：\n"
            "・ご年収（世帯年収）\n"
            "・自己資金の額\n"
            "・ご希望の借入額\n"
            "・返済期間\n\n"
            "プライバシーは厳守いたします🔒"
        ),
        "chat_consultation": (
            "💬 チャット相談\n\n"
            "キノエデザインのスタッフが対応いたします。\n\n"
            "【対応時間】\n"
            "平日：9:00〜18:00\n"
            "土日祝：9:00〜18:00\n"
            "定休日：水曜日\n\n"
            "住まいに関するご相談、ご質問など\n"
            "お気軽にメッセージをお送りください。\n\n"
            "営業時間外の場合は、翌営業日に返信いたします📱"
        ),
        "general": None  # 一般メッセージはRAG処理へ
    }
    
    return responses.get(action)

async def process_message(message_text: str, user_id: str) -> str:
    """メッセージを処理して応答を生成"""
    try:
        # リッチメニューアクションを検出
        action = detect_richmenu_action(message_text)
        
        # リッチメニュー用の定型応答がある場合
        richmenu_response = get_richmenu_response(action, user_id)
        if richmenu_response:
            return richmenu_response
        
        # AI相談または一般的な質問の場合はRAG処理
        if action in ["ai_consultation", "general"]:
            # AI相談開始メッセージの場合は、定型応答
            if action == "ai_consultation" and len(message_text) < 50:
                return get_richmenu_response("ai_consultation", user_id)
            
            # RAG処理
            return await process_rag_query(message_text, user_id)
        
        # その他の場合も一般的なRAG処理
        return await process_rag_query(message_text, user_id)
        
    except Exception as e:
        logger.error(f"Error processing message: {e}")
        logger.error(traceback.format_exc())
        return "申し訳ございません。メッセージの処理中にエラーが発生しました。しばらくしてから再度お試しください。"

async def process_rag_query(message_text: str, user_id: str) -> str:
    """RAGを使用してメッセージを処理"""
    try:
        globals_dict = get_app_globals()
        vectorstore = globals_dict['vectorstore']
        rag_chain_template = globals_dict['rag_chain_template']
        llm_instance = globals_dict['llm_instance']

        logger.info(f"Processing LINE message with RAG: {message_text[:50]}...")

        if not vectorstore and not llm_instance:
            return "申し訳ございません。システムが準備中です。しばらくしてから再度お試しください。"

        # 一般的な挨拶は簡単な応答
        greetings = ["こんにちは", "こんばんは", "おはよう", "はじめまして", "よろしく"]
        if any(greeting in message_text for greeting in greetings):
            return "こんにちは！キノエデザインの住まいAIコンシェルジュです。住まいづくりのご質問をお気軽にどうぞ！🏠"

        if vectorstore and rag_chain_template:
            try:
                logger.info("Using RAG chain for query processing")
               
                if hasattr(rag_chain_template, '__call__'):
                    result = rag_chain_template({"query": message_text})
                elif hasattr(rag_chain_template, 'invoke'):
                    result = rag_chain_template.invoke({"query": message_text})
                else:
                    result = rag_chain_template({"query": message_text}, callbacks=[])
               
                answer = result.get("result", "")
               
                if not answer or "関連する情報が見つかりませんでした" in answer:
                    logger.info("No relevant documents found, trying web search")
                    try:
                        from utils.web_search import GoogleSearcher
                        web_searcher = GoogleSearcher()
                        answer = web_searcher.get_enhanced_answer(
                            message_text, context="", use_web_search=True
                        )
                    except Exception as web_error:
                        logger.error(f"Web search error: {web_error}")
                        answer = "申し訳ございません。関連する情報が見つかりませんでした。"
               
                # LINEメッセージの文字数制限を考慮
                if len(answer) > 1800:
                    answer = answer[:1800] + "...\n\n詳細については、お気軽にお尋ねください。"
               
                return answer
               
            except Exception as e:
                logger.error(f"RAG chain error: {e}")
                if llm_instance:
                    return get_general_response_from_llm(message_text, llm_instance)
                else:
                    return "申し訳ございません。質問の処理中にエラーが発生しました。"
        else:
            if llm_instance:
                return get_general_response_from_llm(message_text, llm_instance)
            else:
                return "申し訳ございません。システムが準備中です。しばらくしてから再度お試しください。"

    except Exception as e:
        logger.error(f"Error processing RAG query: {e}")
        logger.error(traceback.format_exc())
        return "システムエラーが発生しました。管理者にお問い合わせください。"

def get_general_response_from_llm(query: str, llm_instance):
    """一般的な質問への回答を生成"""
    try:
        prompt = f"""あなたはキノエデザインの住まいAIコンシェルジュです。
お客様からの以下の質問に、親切で分かりやすい日本語で回答してください。

質問: {query}

回答:"""
       
        if hasattr(llm_instance, 'invoke'):
            response = llm_instance.invoke(prompt)
            return response.content if hasattr(response, 'content') else str(response)
        else:
            response = llm_instance(prompt)
            return response if isinstance(response, str) else str(response)
           
    except Exception as e:
        logger.error(f"Error generating general response: {e}")
        return "申し訳ございません。回答の生成中にエラーが発生しました。"

# Webhook エンドポイント
@router.post("/webhook")
async def line_webhook(request: Request):
    """LINE Webhook エンドポイント (v3対応)"""
    if not line_bot_api or not handler:
        raise HTTPException(status_code=500, detail="LINE Bot not configured")
   
    body = await request.body()
    signature = request.headers.get("X-Line-Signature", "")
   
    try:
        handler.handle(body.decode('utf-8'), signature)
    except InvalidSignatureError:
        logger.error("Invalid signature")
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
   
    return {"status": "ok"}

# イベントハンドラー (v3対応)
if LINE_SDK_AVAILABLE and handler:
    @handler.add(MessageEvent, message=TextMessageContent)
    def handle_text_message(event):
        """テキストメッセージの処理 (v3対応)"""
        try:
            user_id = event.source.user_id
            message_text = event.message.text
           
            logger.info(f"Received LINE message from {user_id}: {message_text}")
           
            # メッセージを処理
            answer = asyncio.run(process_message(message_text, user_id))
           
            # v3対応のメッセージ送信
            with ApiClient(Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)) as api_client:
                line_bot_api = MessagingApi(api_client)
                line_bot_api.reply_message_with_http_info(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=answer)]
                    )
                )
           
            logger.info(f"Sent reply to {user_id}: {answer[:50]}...")
           
        except Exception as e:
            logger.error(f"Error handling text message: {e}")
            logger.error(traceback.format_exc())
           
            try:
                error_message = "申し訳ございません。一時的にエラーが発生しています。しばらくしてから再度お試しください。"
                with ApiClient(Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)) as api_client:
                    line_bot_api = MessagingApi(api_client)
                    line_bot_api.reply_message_with_http_info(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text=error_message)]
                        )
                    )
            except:
                pass

    @handler.add(FollowEvent)
    def handle_follow(event):
        """友達追加時の処理 (v3対応)"""
        try:
            user_id = event.source.user_id
            logger.info(f"New follower: {user_id}")
           
            welcome_message = (
                "友達追加ありがとうございます！🎉\n\n"
                "キノエデザインの住まいAIコンシェルジュです。\n\n"
                "画面下のメニューから各種サービスをご利用いただけます：\n"
                "🤖 AI相談：住まいに関する質問\n"
                "📋 資料請求：カタログ送付\n"
                "📍 展示場予約：見学予約\n"
                "💰 資金計画：ローン相談\n\n"
                "どうぞお気軽にご利用ください！"
            )
           
            with ApiClient(Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)) as api_client:
                line_bot_api = MessagingApi(api_client)
                line_bot_api.reply_message_with_http_info(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=welcome_message)]
                    )
                )
           
        except Exception as e:
            logger.error(f"Error handling follow event: {e}")

# 管理・テスト用エンドポイント
@router.get("/status")
def get_line_bot_status():
    """LINE Bot の状態確認"""
    return {
        "line_bot_configured": bool(line_bot_api and handler),
        "line_sdk_available": LINE_SDK_AVAILABLE,
        "line_sdk_version": "3.5.0",
        "channel_access_token_set": bool(LINE_CHANNEL_ACCESS_TOKEN),
        "channel_secret_set": bool(LINE_CHANNEL_SECRET),
        "timestamp": datetime.now().isoformat()
    }

@router.get("/test")
def test_line_bot_connection():
    """LINE Bot API接続テスト"""
    if not LINE_SDK_AVAILABLE:
        return {
            "status": "error",
            "message": "LINE Bot SDK not available. Please install: pip install line-bot-sdk==3.5.0",
            "config": {
                "access_token_set": bool(LINE_CHANNEL_ACCESS_TOKEN),
                "channel_secret_set": bool(LINE_CHANNEL_SECRET)
            }
        }
   
    if not line_bot_api:
        return {
            "status": "error",
            "message": "LINE Bot not configured",
            "config": {
                "access_token_set": bool(LINE_CHANNEL_ACCESS_TOKEN),
                "channel_secret_set": bool(LINE_CHANNEL_SECRET)
            }
        }
   
    try:
        return {
            "status": "success",
            "message": "LINE Bot API is configured correctly (SDK v3.5.0)",
            "webhook_url": "https://your-domain.com/line/webhook",
            "config": {
                "access_token_set": bool(LINE_CHANNEL_ACCESS_TOKEN),
                "channel_secret_set": bool(LINE_CHANNEL_SECRET)
            }
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"LINE Bot API test failed: {str(e)}"
        }