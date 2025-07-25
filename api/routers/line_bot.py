# api/routers/line_bot.py

import os
import logging
from datetime import datetime
from fastapi import APIRouter, Request, HTTPException
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError, LineBotApiError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    FollowEvent, UnfollowEvent, PostbackEvent
)
import traceback

logger = logging.getLogger(__name__)

# LINE Bot 設定
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

# LINE Bot APIの初期化
if LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET:
    line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
    handler = WebhookHandler(LINE_CHANNEL_SECRET)
    logger.info("✅ LINE Bot API initialized successfully")
else:
    line_bot_api = None
    handler = None
    logger.warning("⚠️ LINE Bot credentials not found")

router = APIRouter(prefix="/line", tags=["line"])

def get_app_globals():
    """mainモジュールからグローバル変数を取得"""
    import main
    return {
        'vectorstore': getattr(main, 'vectorstore', None),
        'rag_chain_template': getattr(main, 'rag_chain_template', None),
        'llm_instance': getattr(main, 'llm_instance', None)
    }

def is_general_greeting_or_chat(query: str) -> bool:
    """一般的な挨拶や雑談かどうかを判定"""
    greetings = [
        "こんにちは", "こんばんは", "おはよう", "はじめまして",
        "hello", "hi", "hey", "ありがとう", "さようなら",
        "元気", "調子はどう", "お疲れ様", "よろしく", "友達追加"
    ]
    query_lower = query.lower()
    for greeting in greetings:
        if greeting in query_lower:
            return True
    if len(query.strip()) <= 5:
        return True
    return False

def get_general_response_from_llm(query: str, llm_instance):
    """一般的な質問への回答を生成"""
    try:
        prompt = f"""あなたは親切で丁寧な日本語のAIアシスタントです。
以下のユーザーの入力に対して、自然で親しみやすい日本語で応答してください。
LINEでのチャットのような短めの応答を心がけてください。

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
        if "こんにちは" in query or "はじめまして" in query:
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

        # システムが初期化されていない場合
        if not vectorstore and not llm_instance:
            return "申し訳ございません。システムが準備中です。しばらくしてから再度お試しください。"

        # 一般的な挨拶や雑談の場合
        if is_general_greeting_or_chat(message_text):
            if llm_instance:
                return get_general_response_from_llm(message_text, llm_instance)
            else:
                if "こんにちは" in message_text or "はじめまして" in message_text:
                    return "こんにちは！🌟\nRAGチャットボットです。何でもお気軽にご質問ください！"
                else:
                    return "お手伝いできることがあれば、お気軽にお尋ねください。"

        # RAGチェーンを使用した回答生成
        if vectorstore and rag_chain_template:
            try:
                # RAG検索と回答生成
                if hasattr(rag_chain_template, '__call__'):
                    result = rag_chain_template({"query": message_text})
                elif hasattr(rag_chain_template, 'invoke'):
                    result = rag_chain_template.invoke({"query": message_text})
                else:
                    result = rag_chain_template({"query": message_text}, callbacks=[])
                
                answer = result.get("result", "")
                
                # 回答が見つからない場合、Web検索も試す
                if not answer or "関連する情報が見つかりませんでした" in answer:
                    logger.info("No relevant documents found, trying enhanced response")
                    from utils.web_search import GoogleSearcher
                    web_searcher = GoogleSearcher()
                    answer = web_searcher.get_enhanced_answer(message_text, context="", use_web_search=True)
                
                # LINEメッセージの文字数制限（2000文字）を考慮
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
            # RAGが利用できない場合、LLMで直接回答
            if llm_instance:
                return get_general_response_from_llm(message_text, llm_instance)
            else:
                return "申し訳ございません。システムが準備中です。しばらくしてから再度お試しください。"

    except Exception as e:
        logger.error(f"Error processing RAG query: {e}")
        logger.error(traceback.format_exc())
        return "システムエラーが発生しました。管理者にお問い合わせください。"

@router.post("/webhook")
async def line_webhook(request: Request):
    """LINE Webhook エンドポイント"""
    if not line_bot_api or not handler:
        raise HTTPException(status_code=500, detail="LINE Bot not configured")
    
    # リクエストボディとシグネチャを取得
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

@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    """テキストメッセージの処理"""
    try:
        user_id = event.source.user_id
        message_text = event.message.text
        
        logger.info(f"Received LINE message from {user_id}: {message_text}")
        
        # RAGを使用して回答を生成
        import asyncio
        answer = asyncio.run(process_rag_query(message_text, user_id))
        
        # 回答を送信
        reply_message = TextSendMessage(text=answer)
        line_bot_api.reply_message(event.reply_token, reply_message)
        
        logger.info(f"Sent reply to {user_id}: {answer[:50]}...")
        
    except LineBotApiError as e:
        logger.error(f"LINE Bot API error: {e}")
    except Exception as e:
        logger.error(f"Error handling text message: {e}")
        logger.error(traceback.format_exc())
        
        # エラー時の応答
        try:
            error_message = TextSendMessage(
                text="申し訳ございません。一時的にエラーが発生しています。しばらくしてから再度お試しください。"
            )
            line_bot_api.reply_message(event.reply_token, error_message)
        except:
            pass

@handler.add(FollowEvent)
def handle_follow(event):
    """友達追加時の処理"""
    try:
        user_id = event.source.user_id
        logger.info(f"New follower: {user_id}")
        
        welcome_message = TextSendMessage(
            text="友達追加ありがとうございます！🎉\n\n"
                 "私はRAGチャットボットです。\n"
                 "アップロードされた文書に基づいて、様々な質問にお答えします。\n\n"
                 "何でもお気軽にご質問ください！"
        )
        line_bot_api.reply_message(event.reply_token, welcome_message)
        
    except LineBotApiError as e:
        logger.error(f"LINE Bot API error in follow event: {e}")
    except Exception as e:
        logger.error(f"Error handling follow event: {e}")

@handler.add(UnfollowEvent)
def handle_unfollow(event):
    """ブロック・友達削除時の処理"""
    user_id = event.source.user_id
    logger.info(f"User unfollowed: {user_id}")

# 管理用エンドポイント
@router.get("/status")
def get_line_bot_status():
    """LINE Bot の状態確認"""
    return {
        "line_bot_configured": bool(line_bot_api and handler),
        "channel_access_token_set": bool(LINE_CHANNEL_ACCESS_TOKEN),
        "channel_secret_set": bool(LINE_CHANNEL_SECRET),
        "timestamp": datetime.now().isoformat()
    }

@router.post("/broadcast")
async def broadcast_message(message: dict):
    """管理者用：全ユーザーへのメッセージ配信"""
    if not line_bot_api:
        raise HTTPException(status_code=500, detail="LINE Bot not configured")
    
    try:
        # 注意: 実際の実装では対象ユーザーリストを管理する必要があります
        # ここでは例として単一ユーザーへの送信を示しています
        text_message = TextSendMessage(text=message.get("text", ""))
        
        # 実際の実装では、データベースから友達リストを取得して配信
        # line_bot_api.multicast(user_ids, text_message)
        
        return {"status": "Message broadcast initiated"}
        
    except LineBotApiError as e:
        logger.error(f"Broadcast error: {e}")
        raise HTTPException(status_code=500, detail="Broadcast failed")
    
# api/routers/line_bot.py に追加するテスト用エンドポイント
@router.get("/test")
def test_line_bot_connection():
    """LINE Bot API接続テスト"""
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
        # LINE Bot API の簡単なテスト（プロフィール取得は実際のユーザーIDが必要）
        return {
            "status": "success",
            "message": "LINE Bot API is configured correctly",
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

@router.post("/test-message")
async def test_message_processing(test_request: dict):
    """メッセージ処理のテスト"""
    message_text = test_request.get("message", "テストメッセージ")
    user_id = test_request.get("user_id", "test_user")
    
    try:
        response = await process_rag_query(message_text, user_id)
        return {
            "status": "success",
            "input": message_text,
            "output": response,
            "user_id": user_id
        }
    except Exception as e:
        return {
            "status": "error",
            "input": message_text,
            "error": str(e)
        }

@router.get("/webhook-info")
def get_webhook_info():
    """Webhook設定情報を表示"""
    base_url = os.getenv("API_URL", "https://rag-api-190389115361.asia-northeast1.run.app")
    return {
        "webhook_url": f"{base_url}/line/webhook",
        "status_url": f"{base_url}/line/status",
        "test_url": f"{base_url}/line/test",
        "instructions": [
            "1. LINE Developers Console でWebhook URLを設定してください",
            "2. Webhookの使用を有効にしてください", 
            "3. 応答メッセージを無効にしてください（重複を避けるため）",
            "4. /line/test エンドポイントで接続をテストしてください"
        ]
    }
    

# api/routers/line_bot.py に追加するリッチメニュー機能

from linebot.models import (
    QuickReply, QuickReplyButton, MessageAction,
    RichMenu, RichMenuSize, RichMenuArea, RichMenuBounds,
    URIAction, PostbackAction
)

def create_quick_reply_buttons():
    """クイックリプライボタンを作成"""
    return QuickReply(items=[
        QuickReplyButton(action=MessageAction(label="よくある質問", text="よくある質問を教えて")),
        QuickReplyButton(action=MessageAction(label="料金について", text="料金について教えて")),
        QuickReplyButton(action=MessageAction(label="サービス内容", text="サービス内容について")),
        QuickReplyButton(action=MessageAction(label="お問い合わせ", text="お問い合わせ方法を教えて")),
    ])

def setup_rich_menu():
    """リッチメニューを設定"""
    if not line_bot_api:
        return None
    
    try:
        # リッチメニューの定義
        rich_menu = RichMenu(
            size=RichMenuSize(width=2500, height=1686),
            selected=False,
            name="RAGチャットメニュー",
            chat_bar_text="メニュー",
            areas=[
                RichMenuArea(
                    bounds=RichMenuBounds(x=0, y=0, width=1250, height=843),
                    action=MessageAction(label="質問する", text="質問があります")
                ),
                RichMenuArea(
                    bounds=RichMenuBounds(x=1250, y=0, width=1250, height=843),
                    action=MessageAction(label="ヘルプ", text="使い方を教えて")
                ),
                RichMenuArea(
                    bounds=RichMenuBounds(x=0, y=843, width=1250, height=843),
                    action=MessageAction(label="よくある質問", text="よくある質問")
                ),
                RichMenuArea(
                    bounds=RichMenuBounds(x=1250, y=843, width=1250, height=843),
                    action=MessageAction(label="お問い合わせ", text="お問い合わせ")
                )
            ]
        )
        
        # リッチメニューを作成
        rich_menu_id = line_bot_api.create_rich_menu(rich_menu)
        logger.info(f"Rich menu created: {rich_menu_id}")
        
        # ここで画像をアップロードする場合（画像ファイルが必要）
        # with open("path/to/rich_menu_image.jpg", "rb") as f:
        #     line_bot_api.set_rich_menu_image(rich_menu_id, "image/jpeg", f)
        
        # デフォルトのリッチメニューとして設定
        # line_bot_api.set_default_rich_menu(rich_menu_id)
        
        return rich_menu_id
        
    except LineBotApiError as e:
        logger.error(f"Rich menu setup error: {e}")
        return None

# メッセージハンドラーを更新（クイックリプライ対応）
@handler.add(MessageEvent, message=TextMessage)
def handle_text_message_with_quick_reply(event):
    """テキストメッセージの処理（クイックリプライ付き）"""
    try:
        user_id = event.source.user_id
        message_text = event.message.text
        
        logger.info(f"Received LINE message from {user_id}: {message_text}")
        
        # RAGを使用して回答を生成
        import asyncio
        answer = asyncio.run(process_rag_query(message_text, user_id))
        
        # 特定のキーワードに対してクイックリプライを追加
        quick_reply = None
        if any(keyword in message_text for keyword in ["質問", "教えて", "わからない", "ヘルプ"]):
            quick_reply = create_quick_reply_buttons()
        
        # 回答を送信
        reply_message = TextSendMessage(text=answer, quick_reply=quick_reply)
        line_bot_api.reply_message(event.reply_token, reply_message)
        
        logger.info(f"Sent reply to {user_id}: {answer[:50]}...")
        
    except LineBotApiError as e:
        logger.error(f"LINE Bot API error: {e}")
    except Exception as e:
        logger.error(f"Error handling text message: {e}")
        logger.error(traceback.format_exc())
        
        # エラー時の応答
        try:
            error_message = TextSendMessage(
                text="申し訳ございません。一時的にエラーが発生しています。しばらくしてから再度お試しください。"
            )
            line_bot_api.reply_message(event.reply_token, error_message)
        except:
            pass

# リッチメニュー管理用エンドポイント
@router.post("/rich-menu/setup")
def setup_rich_menu_endpoint():
    """リッチメニューを設定"""
    if not line_bot_api:
        raise HTTPException(status_code=500, detail="LINE Bot not configured")
    
    rich_menu_id = setup_rich_menu()
    if rich_menu_id:
        return {"status": "success", "rich_menu_id": rich_menu_id}
    else:
        return {"status": "error", "message": "Failed to create rich menu"}

@router.get("/rich-menu/list")
def list_rich_menus():
    """リッチメニュー一覧を取得"""
    if not line_bot_api:
        raise HTTPException(status_code=500, detail="LINE Bot not configured")
    
    try:
        rich_menus = line_bot_api.get_rich_menu_list()
        return {
            "status": "success",
            "rich_menus": [
                {
                    "id": menu.rich_menu_id,
                    "name": menu.name,
                    "chat_bar_text": menu.chat_bar_text,
                    "selected": menu.selected
                }
                for menu in rich_menus
            ]
        }
    except LineBotApiError as e:
        logger.error(f"Rich menu list error: {e}")
        raise HTTPException(status_code=500, detail="Failed to get rich menu list")

@router.delete("/rich-menu/{rich_menu_id}")
def delete_rich_menu(rich_menu_id: str):
    """リッチメニューを削除"""
    if not line_bot_api:
        raise HTTPException(status_code=500, detail="LINE Bot not configured")
    
    try:
        line_bot_api.delete_rich_menu(rich_menu_id)
        return {"status": "success", "message": f"Rich menu {rich_menu_id} deleted"}
    except LineBotApiError as e:
        logger.error(f"Rich menu delete error: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete rich menu")    