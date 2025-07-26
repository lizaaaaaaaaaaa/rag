# api/routers/line_bot.py - 修正版

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

logger = logging.getLogger(__name__)

# LINE Bot設定
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

# グローバル変数でAPI clientを保持
line_bot_api = None
handler = None

# LINE Bot APIの初期化
if LINE_SDK_AVAILABLE and LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET:
    try:
        # v3 Configuration（修正：グローバルで設定）
        configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
        handler = WebhookHandler(LINE_CHANNEL_SECRET)
        
        # APIクライアントをグローバルで作成
        line_bot_api = MessagingApi(ApiClient(configuration))
        
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

def is_general_greeting_or_chat(query: str) -> bool:
    """一般的な挨拶や雑談かどうかを判定"""
    greetings = [
        "こんにちは", "こんばんは", "おはよう", "はじめまして",
        "hello", "hi", "hey", "ありがとう", "さようなら",
        "元気", "調子はどう", "お疲れ様", "よろしく", "友達追加", "AI相談"
    ]
    query_lower = query.lower()
    
    if any(greeting in query_lower for greeting in greetings):
        return True
    
    if len(query.strip()) <= 5:
        return True
    
    return False

def get_general_response_from_llm(query: str, llm_instance):
    """一般的な質問への回答を生成"""
    try:
        prompt = f"""あなたは親切で丁寧な日本語のAIアシスタントです。
以下のユーザーの入力に対して、自然で親しみやすい日本語で応答してください。
LINEでのチャットのような短めで親しみやすい応答を心がけてください。

ユーザー: {query}

アシスタント:"""
        
        if hasattr(llm_instance, 'invoke'):
            response = llm_instance.invoke(prompt)
            return response.content if hasattr(response, 'content') else str(response)
        else:
            response = llm_instance(prompt)
            return response if isinstance(response, str) else str(response)
            
    except Exception as e:
        logger.error(f"Error generating general response: {e}")
        
        if "こんにちは" in query or "はじめまして" in query or "AI相談" in query:
            return "こんにちは！🌟\nRAGチャットボットです。何でもお気軽にご質問ください！"
        elif "ありがとう" in query:
            return "どういたしまして！😊\n他にもご質問がございましたら、いつでもお聞きください。"
        else:
            return "申し訳ございません。もう一度お聞かせいただけますか？"

async def process_rag_query(message_text: str, user_id: str) -> str:
    """RAGを使用してメッセージを処理"""
    try:
        globals_dict = get_app_globals()
        vectorstore = globals_dict['vectorstore']
        rag_chain_template = globals_dict['rag_chain_template']
        llm_instance = globals_dict['llm_instance']

        logger.info(f"Processing LINE message: {message_text[:50]}...")

        if not vectorstore and not llm_instance:
            return "申し訳ございません。システムが準備中です。しばらくしてから再度お試しください。"

        if is_general_greeting_or_chat(message_text):
            logger.info("Detected general chat/greeting")
            if llm_instance:
                return get_general_response_from_llm(message_text, llm_instance)
            else:
                if "こんにちは" in message_text or "はじめまして" in message_text or "AI相談" in message_text:
                    return "こんにちは！🌟\nRAGチャットボットです。何でもお気軽にご質問ください！"
                else:
                    return "お手伝いできることがあれば、お気軽にお尋ねください。"

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

# Webhook エンドポイント
@router.post("/webhook")
async def line_webhook(request: Request):
    """LINE Webhook エンドポイント (v3対応・修正版)"""
    if not line_bot_api or not handler:
        logger.error("LINE Bot not configured properly")
        raise HTTPException(status_code=500, detail="LINE Bot not configured")
    
    body = await request.body()
    signature = request.headers.get("X-Line-Signature", "")
    
    logger.info(f"Received webhook: signature={signature[:10]}..., body_size={len(body)}")
    
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

# イベントハンドラー (v3対応・修正版)
if LINE_SDK_AVAILABLE and handler and line_bot_api:
    @handler.add(MessageEvent, message=TextMessageContent)
    def handle_text_message(event):
        """テキストメッセージの処理 (v3対応・修正版)"""
        try:
            user_id = event.source.user_id
            message_text = event.message.text.strip()
            
            logger.info(f"Received LINE message from {user_id}: {message_text}")
            
            # リッチメニューからのメッセージ処理
            if message_text == "🤖 AI相談 AI相談を開始します！ ご質問やお悩みを自由に 入力してください😊":
                # AI相談モードの開始メッセージ
                welcome_message = (
                    "AI相談を開始します！🤖\n\n"
                    "家づくりに関するご質問をお気軽にどうぞ。\n"
                    "例えば：\n"
                    "・「注文住宅の流れを教えて」\n"
                    "・「坪単価はいくらですか？」\n"
                    "・「土地探しのポイントは？」\n\n"
                    "ご質問をお待ちしています！"
                )
                
                # 修正：グローバルのline_bot_apiを使用
                try:
                    line_bot_api.reply_message_with_http_info(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text=welcome_message)]
                        )
                    )
                    logger.info(f"Sent welcome message to {user_id}")
                except Exception as api_error:
                    logger.error(f"Failed to send welcome message: {api_error}")
                
                return
            
            # その他のリッチメニューメッセージ
            elif message_text == "資料請求":
                response_text = "資料請求ありがとうございます。\n担当者より後日ご連絡させていただきます。"
            elif message_text == "展示場予約":
                response_text = "展示場のご予約はこちらから：\n[予約フォームURL]"
            elif message_text == "資金計画相談":
                response_text = "資金計画のご相談を承ります。\nご希望の日時をお知らせください。"
            elif message_text == "チャット相談":
                response_text = "チャット相談を開始します。\nどのようなご相談でしょうか？"
            else:
                # 通常のRAGチャット処理（修正：asyncio.run削除）
                # asyncio.run()は既にイベントループ内で実行されているため使用不可
                import asyncio
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # 既存のループで実行
                    task = asyncio.create_task(process_rag_query(message_text, user_id))
                    answer = None
                    # 同期的に結果を取得する代替方法
                    try:
                        # タスクを待機（ただし同期的に）
                        answer = asyncio.run_coroutine_threadsafe(
                            process_rag_query(message_text, user_id), loop
                        ).result(timeout=30)
                    except Exception as async_error:
                        logger.error(f"Async processing error: {async_error}")
                        answer = "申し訳ございません。処理中にエラーが発生しました。"
                else:
                    # 新しいループで実行
                    answer = asyncio.run(process_rag_query(message_text, user_id))
                
                # 応答を送信
                try:
                    line_bot_api.reply_message_with_http_info(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text=answer)]
                        )
                    )
                    logger.info(f"Sent RAG reply to {user_id}: {answer[:50]}...")
                except Exception as api_error:
                    logger.error(f"Failed to send RAG reply: {api_error}")
                
                return
            
            # リッチメニューからのメッセージに対する返信
            try:
                line_bot_api.reply_message_with_http_info(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=response_text)]
                    )
                )
                logger.info(f"Sent response to {user_id}: {response_text}")
            except Exception as api_error:
                logger.error(f"Failed to send response: {api_error}")
            
        except Exception as e:
            logger.error(f"Error handling text message: {e}")
            logger.error(traceback.format_exc())
            
            try:
                error_message = "申し訳ございません。一時的にエラーが発生しています。しばらくしてから再度お試しください。"
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
        """友達追加時の処理 (v3対応・修正版)"""
        try:
            user_id = event.source.user_id
            logger.info(f"New follower: {user_id}")
            
            welcome_message = ("友達追加ありがとうございます！🎉\n\n"
                             "私はRAGチャットボットです。\n"
                             "アップロードされた文書に基づいて、様々な質問にお答えします。\n\n"
                             "何でもお気軽にご質問ください！")
            
            try:
                line_bot_api.reply_message_with_http_info(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=welcome_message)]
                    )
                )
                logger.info(f"Sent welcome message to new follower: {user_id}")
            except Exception as api_error:
                logger.error(f"Failed to send welcome message to follower: {api_error}")
            
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
            "webhook_url": "https://rag-api-190389115361.asia-northeast1.run.app/line/webhook",
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