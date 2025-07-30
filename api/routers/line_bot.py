# api/routers/line_bot.py - 修正版（回答クリーンアップ強化）

import os
import logging
import traceback
import re
from datetime import datetime
from fastapi import APIRouter, Request, HTTPException

# asyncio問題を回避するための対策
import asyncio
import threading

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
        # v3 Configuration
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
        "元気", "調子はどう", "お疲れ様", "よろしく", "友達追加"
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
        
        if "こんにちは" in query or "はじめまして" in query:
            return "こんにちは！🌟\nRAGチャットボットです。何でもお気軽にご質問ください！"
        elif "ありがとう" in query:
            return "どういたしまして！😊\n他にもご質問がございましたら、いつでもお聞きください。"
        else:
            return "申し訳ございません。もう一度お聞かせいただけますか？"

def clean_line_response(raw_response: str) -> str:
    """LINE用のレスポンスクリーンアップ（改良版）"""
    
    if not raw_response or len(raw_response.strip()) < 3:
        return "申し訳ございません。お答えできませんでした。"
    
    # 1. 構造化情報とデバッグ情報の完全削除
    debug_patterns = [
        r"関連文書が見つかりました[:：]?\s*",
        r"関連情報が見つかりました[:：]?\s*",
        r"\d+\.\s*【質問】[^】]*】\s*",
        r"【回答】\s*",
        r"【質問】\s*",
        r"出典[:：]\s*[^\n]*",
        r"/tmp/tmp[a-zA-Z0-9_]*\.pdf",
        r"\([pP]\d+\)",
        r"^\d+\.\s*",
        r"【[^】]*】",
        r"^質問[:：]\s*",
        r"^回答[:：]\s*",
        r"出典[:：][^\n]*",
        r"\.pdf\s*\([pP]\d+\)",
        r"\.pdf\s+\(p\d+\)",
    ]
    
    cleaned = raw_response
    for pattern in debug_patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.MULTILINE | re.IGNORECASE)
    
    # 2. 縦書き文字の修正（LINE専用改良版）
    lines = cleaned.split('\n')
    char_accumulator = []
    fixed_content = []
    
    for line in lines:
        line = line.strip()
        
        if not line:
            # 空行で区切り
            if char_accumulator:
                combined = ''.join(char_accumulator)
                if len(combined) > 3:
                    fixed_content.append(combined)
                char_accumulator = []
            continue
        
        # 1文字の行は蓄積
        if len(line) == 1:
            char_accumulator.append(line)
        else:
            # まとまった文章が来た場合
            if char_accumulator:
                combined = ''.join(char_accumulator)
                if len(combined) > 3:
                    fixed_content.append(combined)
                char_accumulator = []
            
            # 現在の行を追加
            fixed_content.append(line)
    
    # 最後の蓄積分を処理
    if char_accumulator:
        combined = ''.join(char_accumulator)
        if len(combined) > 3:
            fixed_content.append(combined)
    
    # 3. 重複除去と最適化
    if fixed_content:
        # 重複する行を除去
        unique_lines = []
        seen = set()
        
        for line in fixed_content:
            line_norm = re.sub(r'[。、\s]', '', line.lower())
            if line_norm not in seen and len(line) > 5:
                seen.add(line_norm)
                unique_lines.append(line)
        
        # 最も長い有意な内容を選択
        if unique_lines:
            best_line = max(unique_lines, key=len)
            result = best_line
        else:
            result = fixed_content[0] if fixed_content else ""
    else:
        result = "申し訳ございません。お答えできませんでした。"
    
    # 4. 最終整形
    result = re.sub(r'\s+', ' ', result)
    result = re.sub(r'([。！？])\s*', r'\1', result)
    result = result.strip()
    
    # 文末調整
    if result and not result.endswith(('。', '！', '？')):
        if result.endswith('、'):
            result = result[:-1] + '。'
        elif not result.endswith('.'):
            result += '。'
    
    # LINEメッセージの文字数制限
    if len(result) > 1800:
        result = result[:1800] + "...\n\n詳細については、お気軽にお尋ねください。"
    
    # 最低限の内容チェック
    if len(result) < 10:
        result = "申し訳ございません。詳細についてはお問い合わせください。"
    
    return result

def process_rag_query_sync(message_text: str, user_id: str) -> str:
    """RAGを使用してメッセージを処理（改良版）"""
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
                if "こんにちは" in message_text or "はじめまして" in message_text:
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
                
                raw_answer = result.get("result", "")
                logger.info(f"Raw RAG response for LINE: {raw_answer[:100]}...")
                
                # LINE専用のクリーンアップを適用
                answer = clean_line_response(raw_answer)
                logger.info(f"Cleaned LINE response: {answer[:100]}...")
                
                if not answer or "関連する情報が見つかりませんでした" in answer:
                    logger.info("No relevant documents found, trying web search")
                    try:
                        from utils.web_search import GoogleSearcher
                        web_searcher = GoogleSearcher()
                        answer = web_searcher.get_enhanced_answer(
                            message_text, context="", use_web_search=True
                        )
                        # Web検索結果もクリーンアップ
                        answer = clean_line_response(answer)
                    except Exception as web_error:
                        logger.error(f"Web search error: {web_error}")
                        answer = "申し訳ございません。関連する情報が見つかりませんでした。"
                
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
    """LINE Webhook エンドポイント (v3対応)"""
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

# イベントハンドラー (v3対応・リッチメニュー完全対応版)
if LINE_SDK_AVAILABLE and handler and line_bot_api:
    @handler.add(MessageEvent, message=TextMessageContent)
    def handle_text_message(event):
        """テキストメッセージの処理 (v3対応・改良版)"""
        try:
            user_id = event.source.user_id
            message_text = event.message.text.strip()
            
            logger.info(f"Received LINE message from {user_id}: {message_text}")
            
            # リッチメニューからのメッセージ処理
            response_text = None
            
            # リッチメニューボタンの判定（部分一致で対応）
            if "AI相談" in message_text:
                response_text = (
                    "AI相談を開始します！🤖\n\n"
                    "ご質問やお悩みを自由に入力してください😊\n"
                    "例えば：\n"
                    "・おすすめの住宅設計は？\n"
                    "・価格について教えて\n"
                    "・アフターサービスについて\n\n"
                    "どんなことでもお気軽にどうぞ！"
                )
                
            elif "AI住まいサイト" in message_text:
                response_text = (
                    "AI住まいサイトは現在準備中です🏗️\n\n"
                    "近日公開予定ですので、もうしばらくお待ちください。\n"
                    "公開されましたらお知らせいたします！\n\n"
                    "他にご質問がございましたら、お気軽にお尋ねください😊"
                )
                
            elif "資料請求" in message_text:
                response_text = (
                    "資料請求を承ります📋\n\n"
                    "以下の情報をお送りください：\n"
                    "1. お名前（フルネーム）\n"
                    "2. 郵便番号\n"
                    "3. ご住所\n"
                    "4. お電話番号\n\n"
                    "例：\n"
                    "山田太郎\n"
                    "〒123-4567\n"
                    "東京都渋谷区〇〇1-2-3\n"
                    "090-1234-5678"
                )
                
            elif "展示場" in message_text and "予約" in message_text:
                response_text = (
                    "展示場のご予約を承ります📍\n\n"
                    "ご希望の日時をお知らせください。\n"
                    "営業時間：9:00〜18:00\n\n"
                    "例：\n"
                    "「1月15日（水）14時に予約したいです」\n\n"
                    "※土日は混雑することがございます。\n"
                    "平日のご来場がおすすめです😊"
                )
                
            elif "資金計画" in message_text:
                response_text = (
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
                
            elif "チャット相談" in message_text:
                response_text = (
                    "チャット相談を開始します💬\n\n"
                    "スタッフが対応いたします。\n"
                    "お気軽にご相談内容をお送りください！\n\n"
                    "営業時間：9:00〜18:00\n"
                    "※営業時間外のメッセージは翌営業日に返信いたします。"
                )
            
            # 個人情報の入力への対応
            elif any(keyword in message_text for keyword in ["〒", "郵便番号", "住所"]) and len(message_text) > 20:
                response_text = (
                    "資料請求を受け付けました📮\n\n"
                    "ご記入いただいた住所に資料をお送りいたします。\n"
                    "到着まで3〜5営業日ほどお待ちください。\n\n"
                    "ご不明な点がございましたら、お気軽にお問い合わせください😊"
                )
                
            elif any(keyword in message_text for keyword in ["月", "日", "時", "予約"]) and "展示場" not in message_text and len(message_text) > 10:
                response_text = (
                    "展示場のご予約を承りました📍\n\n"
                    "ご希望の日時で仮予約いたしました。\n"
                    "確定後、改めてご連絡いたします。\n\n"
                    "当日は以下をご持参ください：\n"
                    "・ご家族の情報\n"
                    "・ご希望の間取りイメージ\n"
                    "・ご予算の目安\n\n"
                    "お会いできるのを楽しみにしています！"
                )
            
            # 通常のメッセージ（RAGチャット処理）
            if not response_text:
                # RAG処理を呼び出し（改良版クリーンアップ適用）
                response_text = process_rag_query_sync(message_text, user_id)
            
            # 応答を送信
            try:
                line_bot_api.reply_message_with_http_info(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=response_text)]
                    )
                )
                logger.info(f"Sent response to {user_id}: {response_text[:50]}...")
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
        """友達追加時の処理 (v3対応)"""
        try:
            user_id = event.source.user_id
            logger.info(f"New follower: {user_id}")
            
            welcome_message = (
                "友達追加ありがとうございます！🎉\n\n"
                "キノエデザインホームです。\n"
                "家づくりに関するご相談を承っております。\n\n"
                "下のメニューから、お好きな項目をお選びください：\n"
                "A: AI相談 - AIが質問に即座に回答\n"
                "B: AI住まいサイト - 準備中\n"
                "C: 資料請求 - パンフレットをお送りします\n"
                "D: 展示場予約 - 実際の家を見学\n"
                "E: 資金計画 - お金の相談\n"
                "F: チャット相談 - スタッフと直接相談\n\n"
                "お気軽にご利用ください！"
            )
            
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