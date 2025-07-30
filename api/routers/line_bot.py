# api/routers/line_bot.py - 改善版（完全な回答生成）

import os
import logging
import traceback
import re
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
    logger.info("✅ LINE Bot SDK v3.5.0 loaded successfully")
    
except ImportError as e:
    logging.getLogger(__name__).error(f"LINE Bot SDK not available: {e}")
    LINE_SDK_AVAILABLE = False

# LINE Bot設定
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

# グローバル変数でAPI clientを保持
line_bot_api = None
handler = None

# LINE Bot APIの初期化
if LINE_SDK_AVAILABLE and LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET:
    try:
        configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
        handler = WebhookHandler(LINE_CHANNEL_SECRET)
        line_bot_api = MessagingApi(ApiClient(configuration))
        logger.info("✅ LINE Bot API v3 initialized successfully")
    except Exception as e:
        logger.error(f"❌ LINE Bot API initialization failed: {e}")
        line_bot_api = None
        handler = None

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
            return "こんにちは！🌟\nキノエデザインホームのAIアシスタントです。住宅に関することなら何でもお気軽にご質問ください！"
        elif "ありがとう" in query:
            return "どういたしまして！😊\n他にもご質問がございましたら、いつでもお聞きください。"
        else:
            return "申し訳ございません。もう一度お聞かせいただけますか？"

def clean_line_response_advanced(raw_response: str) -> str:
    """LINE用の高度なレスポンスクリーンアップ"""
    
    if not raw_response or len(raw_response.strip()) < 3:
        return "申し訳ございません。お答えできませんでした。"
    
    # 1. デバッグ情報とメタデータの完全削除
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
        r"参考文献[:：][^\n]*",
        r"ソース[:：][^\n]*",
        r"情報源[:：][^\n]*",
    ]
    
    cleaned = raw_response
    for pattern in debug_patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.MULTILINE | re.IGNORECASE)
    
    # 2. 縦書き文字の完全修正（改良版）
    lines = cleaned.split('\n')
    horizontal_content = []
    vertical_buffer = []
    
    for line in lines:
        line = line.strip()
        
        # 空行で区切り
        if not line:
            if vertical_buffer:
                combined = ''.join(vertical_buffer)
                if len(combined) > 5:  # 意味のある長さのもののみ
                    horizontal_content.append(combined)
                vertical_buffer = []
            continue
        
        # 1文字または2文字の短い行は縦書きとして蓄積
        if len(line) <= 2:
            vertical_buffer.append(line)
        else:
            # 通常の文章
            if vertical_buffer:
                combined = ''.join(vertical_buffer)
                if len(combined) > 5:
                    horizontal_content.append(combined)
                vertical_buffer = []
            horizontal_content.append(line)
    
    # 最後のバッファを処理
    if vertical_buffer:
        combined = ''.join(vertical_buffer)
        if len(combined) > 5:
            horizontal_content.append(combined)
    
    # 3. 重複排除と内容の最適化
    if horizontal_content:
        unique_content = []
        seen_normalized = set()
        
        for content in horizontal_content:
            if len(content) < 10:  # 短すぎる内容はスキップ
                continue
                
            # 正規化（句読点と空白を除去）
            normalized = re.sub(r'[。、\s]', '', content.lower())
            
            # 重複チェック
            is_duplicate = False
            for seen in seen_normalized:
                similarity = len(set(normalized) & set(seen)) / max(len(set(normalized)), len(set(seen)), 1)
                if similarity > 0.8:  # 80%以上似ている場合は重複とみなす
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                seen_normalized.add(normalized)
                unique_content.append(content)
        
        # 最も情報量の多い内容を選択
        if unique_content:
            # 長さと質を考慮して最適な回答を選択
            best_content = max(unique_content, key=lambda x: len(x) + x.count('。') * 10)
            result = best_content
        else:
            result = horizontal_content[0] if horizontal_content else ""
    else:
        result = "申し訳ございません。お答えできませんでした。"
    
    # 4. 最終的な文章の整形
    if result:
        # 余分な空白の削除
        result = re.sub(r'\s+', ' ', result)
        # 句読点の後の空白を削除
        result = re.sub(r'([。！？])\s*', r'\1', result)
        result = result.strip()
        
        # 文末の調整
        if result and not result.endswith(('。', '！', '？', '.')):
            if result.endswith('、'):
                result = result[:-1] + '。'
            else:
                result += '。'
    
    # 5. LINEメッセージの文字数制限（2000文字）
    if len(result) > 1800:
        result = result[:1800] + "...\n\n詳細については、お気軽にお尋ねください。"
    
    # 6. 最低限の内容チェック
    if len(result) < 15:
        result = "申し訳ございません。お尋ねの内容について、詳細な情報をお答えできませんでした。よろしければ、別の表現で再度お聞かせください。"
    
    return result

def process_rag_query_safe(message_text: str, user_id: str) -> str:
    """安全なRAG処理（エラーハンドリング強化版）"""
    try:
        logger.info(f"Processing LINE message: {message_text[:50]}...")
        
        globals_dict = get_app_globals()
        vectorstore = globals_dict['vectorstore']
        rag_chain_template = globals_dict['rag_chain_template']
        llm_instance = globals_dict['llm_instance']

        if not vectorstore and not llm_instance:
            return "申し訳ございません。システムが準備中です。しばらくしてから再度お試しください。"

        # 一般的な挨拶の場合
        if is_general_greeting_or_chat(message_text):
            logger.info("Detected general chat/greeting")
            if llm_instance:
                return get_general_response_from_llm(message_text, llm_instance)
            else:
                if "こんにちは" in message_text or "はじめまして" in message_text:
                    return "こんにちは！🌟\nキノエデザインホームのAIアシスタントです。住宅に関することなら何でもお気軽にご質問ください！"
                else:
                    return "お手伝いできることがあれば、お気軽にお尋ねください。"

        # RAGチェーンを使用
        if vectorstore and rag_chain_template:
            try:
                logger.info("Using RAG chain for query processing")
                
                # RAGチェーンを実行
                if hasattr(rag_chain_template, 'invoke'):
                    result = rag_chain_template.invoke({"query": message_text})
                elif hasattr(rag_chain_template, '__call__'):
                    result = rag_chain_template({"query": message_text})
                else:
                    # フォールバック処理
                    docs = vectorstore.similarity_search(message_text, k=3)
                    if docs:
                        context = "\n".join([doc.page_content for doc in docs[:2]])
                        if llm_instance:
                            prompt = f"""以下の情報を参考に、質問に自然で分かりやすく答えてください。

参考情報: {context}

質問: {message_text}

自然で親しみやすい日本語で回答してください。"""
                            
                            response = llm_instance.invoke(prompt)
                            raw_answer = response.content if hasattr(response, 'content') else str(response)
                        else:
                            raw_answer = f"関連情報が見つかりました: {context[:200]}..."
                    else:
                        raw_answer = "関連する情報が見つかりませんでした。"
                    
                    result = {"result": raw_answer}
                
                raw_answer = result.get("result", "")
                logger.info(f"Raw RAG response: {raw_answer[:100]}...")
                
                # 高度なクリーンアップを適用
                cleaned_answer = clean_line_response_advanced(raw_answer)
                logger.info(f"Cleaned response: {cleaned_answer[:100]}...")
                
                # 回答が不十分な場合のフォールバック
                if not cleaned_answer or len(cleaned_answer) < 20 or "関連する情報が見つかりませんでした" in cleaned_answer:
                    logger.info("No relevant answer, using fallback")
                    if "坪単価" in message_text or "価格" in message_text:
                        cleaned_answer = "坪単価については、お客様のご希望や仕様によって異なります。詳細なお見積りをご提供いたしますので、お気軽にお問い合わせください。"
                    elif "仕様" in message_text or "標準" in message_text:
                        cleaned_answer = "住宅の標準仕様については、高品質な住まいをご提供するため、様々な設備や性能を標準装備としております。詳細は展示場でご確認いただけます。"
                    else:
                        cleaned_answer = "申し訳ございません。詳細については、お気軽にお問い合わせください。専門スタッフが丁寧にご説明いたします。"
                
                return cleaned_answer
                
            except Exception as e:
                logger.error(f"RAG chain error: {e}")
                logger.error(traceback.format_exc())
                # エラー時のフォールバック
                if llm_instance:
                    return get_general_response_from_llm(message_text, llm_instance)
                else:
                    return "申し訳ございません。一時的にエラーが発生しました。しばらくしてから再度お試しください。"
        else:
            # RAGが利用できない場合
            if llm_instance:
                return get_general_response_from_llm(message_text, llm_instance)
            else:
                return "申し訳ございません。システムが準備中です。しばらくしてから再度お試しください。"

    except Exception as e:
        logger.error(f"Critical error in process_rag_query_safe: {e}")
        logger.error(traceback.format_exc())
        return "システムエラーが発生しました。管理者にお問い合わせください。"

# Webhook エンドポイント
@router.post("/webhook")
async def line_webhook(request: Request):
    """LINE Webhook エンドポイント (改善版)"""
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

# イベントハンドラー (改善版)
if LINE_SDK_AVAILABLE and handler and line_bot_api:
    @handler.add(MessageEvent, message=TextMessageContent)
    def handle_text_message(event):
        """テキストメッセージの処理 (改善版)"""
        try:
            user_id = event.source.user_id
            message_text = event.message.text.strip()
            
            logger.info(f"Received LINE message from {user_id}: {message_text}")
            
            # リッチメニューからのメッセージ処理（改良版）
            response_text = None
            
            # より柔軟な部分一致での判定
            if "AI相談" in message_text:
                response_text = (
                    "AI相談を開始します！🤖\n\n"
                    "住宅に関するご質問やお悩みを自由にご入力ください😊\n\n"
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
                    "東京都○○区○○1-2-3\n"
                    "090-1234-5678"
                )
                
            elif "展示場" in message_text and ("予約" in message_text or "来場" in message_text):
                response_text = (
                    "展示場のご予約を承ります📍\n\n"
                    "ご希望の日時をお知らせください。\n"
                    "営業時間：9:00〜18:00\n\n"
                    "例：\n"
                    "「2月15日（木）14時に予約したいです」\n\n"
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
            
            # 通常のメッセージ（RAGチャット処理）
            if not response_text:
                # 安全なRAG処理を呼び出し
                response_text = process_rag_query_safe(message_text, user_id)
            
            # 応答を送信（エラーハンドリング強化）
            try:
                line_bot_api.reply_message_with_http_info(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=response_text)]
                    )
                )
                logger.info(f"Successfully sent response to {user_id}: {response_text[:50]}...")
            except Exception as api_error:
                logger.error(f"Failed to send LINE response: {api_error}")
                logger.error(traceback.format_exc())
            
        except Exception as e:
            logger.error(f"Error handling text message: {e}")
            logger.error(traceback.format_exc())
            
            # エラー時の緊急対応
            try:
                error_message = "申し訳ございません。一時的にエラーが発生しています。しばらくしてから再度お試しください。"
                line_bot_api.reply_message_with_http_info(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=error_message)]
                    )
                )
            except:
                logger.error("Failed to send error message")

    @handler.add(FollowEvent)
    def handle_follow(event):
        """友達追加時の処理 (改善版)"""
        try:
            user_id = event.source.user_id
            logger.info(f"New follower: {user_id}")
            
            welcome_message = (
                "友達追加ありがとうございます！🎉\n\n"
                "キノエデザインホームです。\n"
                "家づくりに関するご相談を承っております。\n\n"
                "下のメニューから、お好きな項目をお選びください：\n"
                "• AI相談 - AIが質問に即座に回答\n"
                "• AI住まいサイト - 準備中\n"
                "• 資料請求 - パンフレットをお送りします\n"
                "• 展示場予約 - 実際の家を見学\n"
                "• 資金計画 - お金の相談\n"
                "• チャット相談 - スタッフと直接相談\n\n"
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
                logger.error(f"Failed to send welcome message: {api_error}")
            
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
            "message": "LINE Bot SDK not available. Please install: pip install line-bot-sdk==3.5.0"
        }
    
    if not line_bot_api:
        return {
            "status": "error",
            "message": "LINE Bot not configured"
        }
    
    return {
        "status": "success",
        "message": "LINE Bot API is configured correctly (SDK v3.5.0)",
        "webhook_url": "https://rag-api-190389115361.asia-northeast1.run.app/line/webhook"
    }