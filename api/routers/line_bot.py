# api/routers/line_bot.py - 完全修正版
# 署名検証エラー対応、トークン型変換、エラーハンドリング改善

import logging
from pathlib import Path
from datetime import datetime
from uuid import uuid4
import traceback
import os
import re
import json
import asyncio
from typing import Dict, Optional, Any
from threading import Thread
import concurrent.futures

from fastapi import APIRouter, HTTPException, Request, BackgroundTasks
from pydantic import BaseModel
from fastapi.responses import StreamingResponse, JSONResponse

# 監視機能
from google.cloud import logging as cloud_logging

# LINE Bot SDK v3 imports
try:
    from linebot.v3 import WebhookHandler
    from linebot.v3.exceptions import InvalidSignatureError
    from linebot.v3.messaging import (
        Configuration,
        ApiClient,
        MessagingApi,
        ReplyMessageRequest,
        TextMessage,
        PushMessageRequest
    )
    from linebot.v3.webhooks import (
        MessageEvent,
        TextMessageContent,
        PostbackEvent,
        FollowEvent,
        UnfollowEvent
    )
    
    LINE_SDK_AVAILABLE = True
    logger = logging.getLogger(__name__)
    logger.info("✅ LINE Bot SDK v3.5.0 loaded successfully")
    
except ImportError as e:
    logging.getLogger(__name__).error(f"LINE Bot SDK not available: {e}")
    LINE_SDK_AVAILABLE = False
    
    # Dummy classes for development without LINE SDK
    class WebhookHandler:
        def __init__(self, *args, **kwargs): pass
        def add(self, *args, **kwargs):
            def decorator(func): return func
            return decorator
        def handle(self, *args, **kwargs): pass

logger = logging.getLogger(__name__)

# ★★★ 重要：トークン正規化関数 ★★★
def normalize_line_token(token: Any) -> str:
    """LINE トークンを安全にstring型に変換"""
    if token is None:
        return ""
    
    # bytes型の場合はデコード
    if isinstance(token, bytes):
        try:
            token = token.decode('utf-8')
        except UnicodeDecodeError:
            logger.error("Failed to decode token from bytes")
            return ""
    
    # 文字列に変換
    token_str = str(token).strip()
    
    # 'Bearer ' プレフィックスが含まれている場合は削除
    if token_str.startswith('Bearer '):
        token_str = token_str[7:].strip()
    
    # 'b'' で囲まれている場合は削除
    if token_str.startswith("b'") and token_str.endswith("'"):
        token_str = token_str[2:-1]
    
    return token_str

# ★★★ JSONシリアライズ対応のユーティリティ関数 ★★★
def make_json_serializable(obj: Any) -> Any:
    """オブジェクトをJSONシリアライズ可能に変換"""
    try:
        if obj is None:
            return None
        elif isinstance(obj, (str, int, float, bool)):
            return obj
        elif isinstance(obj, (list, tuple)):
            return [make_json_serializable(item) for item in obj]
        elif isinstance(obj, dict):
            return {str(k): make_json_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, set):
            return list(obj)
        elif hasattr(obj, '__dict__'):
            return make_json_serializable(obj.__dict__)
        elif hasattr(obj, 'isoformat'):
            return obj.isoformat()
        else:
            return str(obj)
    except Exception as e:
        logger.warning(f"Failed to serialize object {type(obj)}: {e}")
        return str(obj)

def safe_json_dumps(obj: Any, **kwargs) -> str:
    """安全なJSON文字列変換"""
    try:
        serializable_obj = make_json_serializable(obj)
        return json.dumps(serializable_obj, ensure_ascii=False, **kwargs)
    except Exception as e:
        logger.error(f"JSON serialization failed: {e}")
        return f'{{"error": "serialization_failed", "type": "{type(obj).__name__}"}}'

# ★★★ 包括的監視システム（修正版） ★★★
class ComprehensiveMonitor:
    def __init__(self):
        self.stats = {
            'webhook_received': 0,
            'postback_events': 0,
            'message_events': 0,
            'follow_events': 0,
            'unfollow_events': 0,
            'errors': 0,
            'send_success': 0,
            'send_failures': 0,
            'richmenu_interactions': {},
            'user_activity': {},
            'response_times': [],
            'last_activity': None,
            'system_health': {
                'cpu_usage': 0,
                'memory_usage': 0,
                'active_connections': 0
            }
        }
        
        # Cloud Logging設定
        try:
            cloud_logging.Client().setup_logging()
            logger.info("✅ Cloud Logging setup completed")
        except Exception as e:
            logger.warning(f"Cloud Logging setup failed: {e}")
    
    def log_webhook_event(self, event_type: str, success: bool = True, event_data: dict = None):
        """包括的なWebhookイベントログ記録（修正版）"""
        self.stats['webhook_received'] += 1
        self.stats['last_activity'] = datetime.now()
        
        # イベントタイプ別カウント
        if event_type == 'postback':
            self.stats['postback_events'] += 1
        elif event_type == 'message':
            self.stats['message_events'] += 1
        elif event_type == 'follow':
            self.stats['follow_events'] += 1
        elif event_type == 'unfollow':
            self.stats['unfollow_events'] += 1
            
        if not success:
            self.stats['errors'] += 1
        
        # 詳細ログデータ（JSONシリアライズ対応）
        log_data = {
            'event_type': event_type,
            'success': success,
            'timestamp': self.stats['last_activity'].isoformat(),
            'error_rate': self.get_error_rate()
        }
        
        # event_dataをシリアライズ可能な形式に変換
        if event_data:
            try:
                log_data['event_data'] = make_json_serializable(event_data)
            except Exception as e:
                logger.warning(f"Failed to serialize event_data: {e}")
                log_data['event_data'] = {"error": "serialization_failed", "type": str(type(event_data))}
        
        try:
            log_message = safe_json_dumps(log_data)
            if not success:
                logger.error(f"LINE Event Error: {log_message}")
            else:
                logger.info(f"LINE Event Success: {log_message}")
        except Exception as e:
            logger.error(f"LINE Event Log Error - Type: {event_type}, Success: {success}, Error: {e}")
    
    def track_send_result(self, success: bool, error_msg: str = None):
        """送信結果の追跡"""
        if success:
            self.stats['send_success'] += 1
        else:
            self.stats['send_failures'] += 1
            if error_msg:
                logger.error(f"Send failure: {error_msg}")
    
    def get_error_rate(self) -> float:
        total_events = max(self.stats['webhook_received'], 1)
        return self.stats['errors'] / total_events
    
    def get_send_success_rate(self) -> float:
        total_sends = self.stats['send_success'] + self.stats['send_failures']
        if total_sends == 0:
            return 1.0
        return self.stats['send_success'] / total_sends

# グローバルインスタンス
monitor = ComprehensiveMonitor()

# ★★★ LINE Bot設定（修正版：トークン正規化） ★★★
def get_normalized_line_credentials():
    """正規化されたLINE認証情報を取得"""
    raw_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    raw_secret = os.getenv("LINE_CHANNEL_SECRET")
    
    # トークンの正規化
    access_token = normalize_line_token(raw_token)
    channel_secret = normalize_line_token(raw_secret)
    
    logger.info(f"Token normalization - Raw type: {type(raw_token)}, Normalized length: {len(access_token)}")
    logger.info(f"Secret normalization - Raw type: {type(raw_secret)}, Normalized length: {len(channel_secret)}")
    
    return access_token, channel_secret

# 正規化された認証情報を取得
LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET = get_normalized_line_credentials()

# LINE Bot APIの初期化（修正版）
if LINE_SDK_AVAILABLE and LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET:
    try:
        # 正規化されたトークンでConfiguration作成
        configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
        handler = WebhookHandler(LINE_CHANNEL_SECRET)
        
        # API クライアントの事前テスト
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            
        logger.info("✅ LINE Bot API v3 initialized successfully")
        logger.info(f"✅ Token length: {len(LINE_CHANNEL_ACCESS_TOKEN)}")
        logger.info(f"✅ Secret length: {len(LINE_CHANNEL_SECRET)}")
        
    except Exception as e:
        logger.error(f"❌ LINE Bot API initialization failed: {e}")
        line_bot_api = None
        handler = None
else:
    line_bot_api = None
    handler = None
    if LINE_SDK_AVAILABLE:
        logger.warning(f"⚠️ LINE Bot credentials not found - Token: {bool(LINE_CHANNEL_ACCESS_TOKEN)}, Secret: {bool(LINE_CHANNEL_SECRET)}")
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

# ★★★ 改良されたメッセージ判定ロジック ★★★
def detect_richmenu_action(message_text: str) -> str:
    """シンプルで寛容なメッセージマッチング（改良版）"""
    text_lower = message_text.lower().replace(" ", "").replace("　", "")
    
    # より多くのパターンに対応
    action_patterns = {
        "ai_consultation": [
            "ai相談", "ai住まい", "相談開始", "質問したい", "聞きたい", 
            "教えて", "ai", "住まい相談", "家について", "ai相談を開始"
        ],
        "document_request": [
            "資料請求", "カタログ", "資料がほしい", "パンフレット",
            "資料送って", "カタログください"
        ],
        "exhibition_reservation": [
            "展示場", "見学", "予約", "来場", "モデルハウス",
            "実際に見たい", "展示場予約"
        ],
        "finance_planning": [
            "資金計画", "ローン", "お金", "費用", "予算",
            "住宅ローン", "資金相談"
        ],
        "chat_consultation": [
            "スタッフ", "人と話したい", "直接相談", "チャット",
            "担当者", "営業"
        ],
        "greeting": [
            "こんにちは", "はじめまして", "よろしく", "おはよう",
            "こんばんは", "hello", "hi"
        ]
    }
    
    # メッセージから最適なアクションを判定
    for action, patterns in action_patterns.items():
        if any(pattern in message_text for pattern in patterns):
            return action
    
    return "general"

def get_richmenu_response(action: str, user_id: str, context: dict = None) -> str:
    """コンテキスト対応のリッチメニュー応答生成"""
    responses = {
        "ai_consultation": """🤖 AI住まい相談を開始します！

キノエデザインの住まいAIコンシェルジュです。
住まいに関するご質問をお気軽にどうぞ！

💡 例えば、こんなご質問にお答えします：
・「坪単価について教えて」
・「標準仕様はどんな感じ？」  
・「耐震性能について知りたい」
・「断熱性能はどのくらい？」
・「間取りのアドバイスが欲しい」
・「住宅ローンについて相談したい」

何でもお聞きください😊""",

        "ai_site": """🌐 AI住まいサイト

キノエデザインのAI住まいサイトにお越しいただき、
ありがとうございます！

現在、より良いサービスをご提供するため
システムの準備中です。

完成次第、こちらでお知らせいたします📢

それまでの間、ご質問は
このチャットでお気軽にお聞きください！""",

        "document_request": """📋 資料請求を承ります

キノエデザインの住まいづくり資料を
お送りいたします。

📝 以下の情報をお送りください：

【必須情報】
1️⃣ お名前（フルネーム）
2️⃣ ご住所（〒郵便番号から）
3️⃣ お電話番号

【ご希望の資料】
🏠 総合カタログ
📸 施工事例集  
📋 標準仕様書
💰 参考価格表

例）「田中太郎、〒123-4567 東京都○○区...、090-1234-5678、総合カタログと事例集希望」

ご入力いただいた後、3営業日以内に
お送りいたします📮""",

        "exhibition_reservation": """📍 展示場来場予約

キノエデザイン展示場への
ご来場予約を承ります！

🏠 展示場情報
【営業時間】9:00-18:00
【定休日】水曜日
【住所】〒XXX-XXXX 住所をここに記載
【TEL】0120-XXX-XXX

📅 ご予約方法
以下をメッセージでお送りください：

・ご希望日時（第1・第2希望）
・お名前
・お電話番号  
・参加人数

例）「1月20日（土）14:00希望、田中太郎、090-1234-5678、大人2名」

実際の住まいをご体感いただけます。
スタッフ一同、お待ちしております🏠✨""",

        "finance_planning": """💰 資金計画・住宅ローン相談

住まいづくりの資金計画を
専門スタッフがサポートいたします！

💡 ご相談内容（例）
・住宅ローンの種類や金利
・月々の返済額シミュレーション  
・頭金の目安
・諸費用について
・フラット35について

📝 以下をお聞かせください：
・ご年収（世帯年収）
・ご用意可能な自己資金
・ご希望借入額
・返済期間のご希望

または📞直通ダイヤル: 0120-XXX-XXX

お客様に最適なプランをご提案いたします。
🔒 個人情報は厳重に管理いたします。""",

        "chat_consultation": """💬 スタッフとチャット相談

キノエデザインのスタッフが
直接ご対応いたします！

【対応時間】
平日・土日祝：9:00-18:00
定休日：水曜日

💭 お気軽にご質問ください：
・住まいづくりの進め方
・土地探しについて
・プランニングのご相談
・施工についてのご質問
・アフターサービスについて

営業時間内でしたら、
できるだけ迅速にお返事いたします📱

営業時間外のメッセージは、
翌営業日にご返答いたします。""",

        "greeting": """こんにちは！
キノエデザインの住まいAIコンシェルジュです🏠

ご挨拶いただき、ありがとうございます😊

画面下のメニューから各種サービスを
ご利用いただけます。

🤖 AI相談：住まいのご質問にAIがお答え
📋 資料請求：カタログ等のご請求
📍 展示場予約：見学のご予約
💰 資金計画：ローンのご相談
💬 チャット相談：スタッフと直接チャット

どうぞお気軽にご利用ください！"""
    }
    
    base_response = responses.get(action)
    if base_response and context:
        current_hour = datetime.now().hour
        if current_hour < 9 or current_hour > 18:
            if action in ["finance_planning", "chat_consultation"]:
                base_response += f"\n\n⏰ 現在は営業時間外です。\n営業開始後（9:00〜）にご回答いたします。"
    return base_response

# ★★★ 緊急時の応答関数 ★★★
def get_emergency_response(message_text: str) -> str:
    """システムエラー時の緊急応答"""
    if any(word in message_text for word in ["こんにちは", "はじめまして", "hello"]):
        return """こんにちは！キノエデザインです🏠

現在システムの調整中ですが、以下のようにメッセージを送っていただければお手伝いできます：

🤖 「AI相談」→ 住まいのご質問にお答えします
📋 「資料請求」→ カタログをお送りします  
📍 「展示場予約」→ 見学のご予約を承ります
💰 「資金計画」→ ローンのご相談
💬 「スタッフ」→ 直接ご相談

どのようなご用件でしょうか？"""

    elif "資料" in message_text or "カタログ" in message_text:
        return """📋 資料請求を承ります

キノエデザインの住まいづくり資料をお送りいたします。
以下の情報をお送りください：

1️⃣ お名前
2️⃣ ご住所（郵便番号から）  
3️⃣ お電話番号
4️⃣ ご希望資料（総合カタログ、施工事例集など）

3営業日以内にお送いいたします📮"""

    else:
        return """申し訳ございません。
システムの調整中でご不便をおかけしています。

お急ぎの場合は以下にご連絡ください：
📞 0120-XXX-XXX
📧 info@kinoe-design.com
⏰ 9:00-18:00（水曜定休）

しばらくしてから再度お試しください。"""

async def process_message(message_text: str, user_id: str) -> str:
    """包括的メッセージ処理システム（デバッグログ強化版）"""
    start_time = datetime.now()
    logger.info(f"🔍 Processing message from {user_id}: '{message_text[:50]}...'")
    try:
        action = detect_richmenu_action(message_text)
        logger.info(f"📱 Detected action: {action}")
        
        richmenu_response = get_richmenu_response(action, user_id)
        if richmenu_response and action != "general":
            response_time = (datetime.now() - start_time).total_seconds()
            logger.info(f"✅ Returned richmenu response for action: {action}")
            return richmenu_response
        
        if action in ["ai_consultation", "general", "greeting"]:
            logger.info(f"🤖 Processing RAG query for action: {action}")
            return await process_rag_query(message_text, user_id)
        
        logger.info(f"🔄 Fallback to RAG processing for action: {action}")
        return await process_rag_query(message_text, user_id)
        
    except Exception as e:
        logger.error(f"❌ Error processing message: {e}")
        logger.error(traceback.format_exc())
        return get_emergency_response(message_text)

async def process_rag_query(message_text: str, user_id: str) -> str:
    """RAGを使用した高度なメッセージ処理（デバッグログ強化版）"""
    try:
        globals_dict = get_app_globals()
        vectorstore = globals_dict['vectorstore']
        rag_chain_template = globals_dict['rag_chain_template']
        llm_instance = globals_dict['llm_instance']

        logger.info(f"🧠 Processing LINE message with RAG - Vectorstore: {vectorstore is not None}, RAG Chain: {rag_chain_template is not None}, LLM: {llm_instance is not None}")

        if not vectorstore and not llm_instance:
            logger.warning("⚠️ Neither vectorstore nor LLM instance available")
            return get_emergency_response(message_text)

        greeting_responses = {
            "こんにちは": "こんにちは！キノエデザインの住まいAIコンシェルジュです。住まいづくりのご質問をお気軽にどうぞ！🏠",
            "こんばんは": "こんばんは！キノエデザインです。住まいに関するご質問がございましたらお聞かせください🌙",
            "おはよう": "おはようございます！キノエデザインです。今日も住まいづくりのお手伝いをさせていただきます☀️",
            "はじめまして": "はじめまして！キノエデザインの住まいAIコンシェルジュです。どうぞよろしくお願いいたします😊",
            "ありがとう": "どういたしまして！他にもご質問がございましたら、いつでもお気軽にお声かけください🙏"
        }
        for greeting, response in greeting_responses.items():
            if greeting in message_text:
                logger.info(f"👋 Detected greeting: {greeting}")
                return response

        if vectorstore and rag_chain_template:
            try:
                logger.info("📚 Using RAG chain for query processing")
                result = None
                if hasattr(rag_chain_template, '__call__'):
                    result = rag_chain_template({"query": message_text})
                elif hasattr(rag_chain_template, 'invoke'):
                    result = rag_chain_template.invoke({"query": message_text})
                else:
                    result = rag_chain_template({"query": message_text}, callbacks=[])
               
                answer = result.get("result", "") if result else ""
                logger.info(f"📝 RAG result length: {len(answer)} characters")
               
                if not answer or "関連する情報が見つかりませんでした" in answer:
                    logger.info("🌐 No relevant documents found, trying web search")
                    try:
                        from utils.web_search import GoogleSearcher
                        web_searcher = GoogleSearcher()
                        answer = web_searcher.get_enhanced_answer(
                            message_text, context="", use_web_search=True
                        )
                        logger.info(f"🔍 Web search enhanced answer length: {len(answer)} characters")
                    except Exception as web_error:
                        logger.error(f"🌐 Web search error: {web_error}")
                        answer = "申し訳ございません。関連する情報が見つかりませんでした。詳しくはスタッフまでお問い合わせください。"
               
                if len(answer) > 1800:
                    answer = answer[:1800] + "...\n\n詳細については、お気軽にお尋ねください。"
                    logger.info("✂️ Answer truncated due to LINE character limit")
               
                return answer
               
            except Exception as e:
                logger.error(f"❌ RAG chain error: {e}")
                logger.error(traceback.format_exc())
                if llm_instance:
                    logger.info("🔄 Falling back to general LLM response")
                    return get_general_response_from_llm(message_text, llm_instance)
                else:
                    return get_emergency_response(message_text)
        else:
            logger.warning("⚠️ RAG not available, trying general LLM")
            if llm_instance:
                return get_general_response_from_llm(message_text, llm_instance)
            else:
                logger.warning("⚠️ No LLM instance available")
                return get_emergency_response(message_text)

    except Exception as e:
        logger.error(f"💥 Error processing RAG query: {e}")
        logger.error(traceback.format_exc())
        return get_emergency_response(message_text)

def get_general_response_from_llm(query: str, llm_instance):
    """一般的な質問への回答を生成（デバッグログ付き）"""
    try:
        logger.info(f"🤖 Generating general LLM response for query: {query[:50]}...")
        prompt = f"""あなたはキノエデザインの住まいAIコンシェルジュです。
お客様からの以下の質問に対して、親切で分かりやすい日本語で回答してください。

住宅・建築に関する専門的な質問の場合は、一般的な知識を基に回答し、
詳細については「専門スタッフにお問い合わせください」と案内してください。

質問: {query}

自然で完全な日本語で回答し、文章は必ず最後まで完結させてください："""
        if hasattr(llm_instance, 'invoke'):
            response = llm_instance.invoke(prompt)
            result = response.content if hasattr(response, 'content') else str(response)
        else:
            response = llm_instance(prompt)
            result = response if isinstance(response, str) else str(response)
        logger.info(f"✅ Generated LLM response length: {len(result)} characters")
        return result
    except Exception as e:
        logger.error(f"❌ Error generating general response: {e}")
        return "申し訳ございません。回答の生成中にエラーが発生しました。スタッフまでお問い合わせください。"

# ★★★ 修正版：安全な返信送信関数 ★★★
def send_line_reply_safe(reply_token: str, message_text: str) -> bool:
    """安全なLINE返信送信（エラーハンドリング強化）"""
    try:
        # トークンの再正規化（安全のため）
        safe_token = normalize_line_token(LINE_CHANNEL_ACCESS_TOKEN)
        
        if not safe_token:
            logger.error("❌ No valid LINE access token available")
            monitor.track_send_result(False, "No valid access token")
            return False
        
        logger.info(f"📤 Sending reply with token length: {len(safe_token)}")
        
        # Configuration を毎回新しく作成（安全のため）
        configuration = Configuration(access_token=safe_token)
        
        with ApiClient(configuration) as api_client:
            messaging_api = MessagingApi(api_client)
            
            # 返信メッセージ送信
            messaging_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=reply_token,
                    messages=[TextMessage(text=message_text)]
                )
            )
        
        logger.info(f"✅ Successfully sent reply (length: {len(message_text)})")
        monitor.track_send_result(True)
        return True
        
    except Exception as e:
        error_msg = f"Failed to send reply: {str(e)}"
        logger.error(f"❌ {error_msg}")
        logger.error(traceback.format_exc())
        monitor.track_send_result(False, error_msg)
        return False

# ★★★ Webhook エンドポイント修正版（署名検証強化）★★★
@router.post("/webhook")
async def line_webhook(request: Request, background_tasks: BackgroundTasks):
    """修正版Webhook エンドポイント（署名検証強化）"""
    logger.info("🚀 LINE Webhook endpoint called")
    
    if not line_bot_api or not handler:
        error_data = {"error": "LINE Bot not configured", "sdk_available": LINE_SDK_AVAILABLE}
        monitor.log_webhook_event("error", False, error_data)
        logger.error("❌ LINE Bot not configured")
        return {"status": "error", "message": "LINE Bot not configured", "timestamp": datetime.now().isoformat()}
    
    try:
        body = await request.body()
        signature = request.headers.get("X-Line-Signature", "")
        logger.info(f"📨 Webhook received - Body length: {len(body)}, Signature exists: {'Yes' if signature else 'No'}")
        
        # 署名が空の場合のエラー処理を改善
        if not signature:
            logger.error("❌ No X-Line-Signature header found")
            error_data = {
                "error": "missing_signature",
                "body_length": len(body),
                "headers": dict(request.headers)
            }
            monitor.log_webhook_event("signature_error", False, error_data)
            return {"status": "error", "message": "Missing signature", "timestamp": datetime.now().isoformat()}
        
        try:
            body_text = body.decode('utf-8')
            logger.info(f"📄 Processing webhook body: {len(body_text)} characters")
            logger.debug(f"Body preview: {body_text[:200]}...")
            
            # 署名検証の強化
            handler.handle(body_text, signature)
            
        except InvalidSignatureError as sig_error:
            logger.error(f"❌ Invalid signature error: {sig_error}")
            # 署名エラーでも500ではなく200で応答（LINEの再送を防ぐ）
            error_data = {
                "error": "invalid_signature",
                "signature_provided": bool(signature),
                "body_length": len(body),
                "signature_preview": signature[:20] if signature else "",
                "error_details": str(sig_error)
            }
            monitor.log_webhook_event("signature_error", False, error_data)
            return {"status": "signature_error", "timestamp": datetime.now().isoformat()}
            
        except Exception as handle_error:
            logger.error(f"❌ Handler error: {handle_error}")
            logger.error(traceback.format_exc())
            error_data = {
                "error": str(handle_error),
                "error_type": type(handle_error).__name__,
                "body_length": len(body)
            }
            monitor.log_webhook_event("handler_error", False, error_data)
            return {"status": "handler_error", "timestamp": datetime.now().isoformat()}
        
        # 成功時のログ
        success_data = {
            "body_length": len(body),
            "processing_time": (datetime.now() - datetime.now()).total_seconds()
        }
        monitor.log_webhook_event("webhook_success", True, success_data)
        logger.info("✅ Webhook processing completed successfully")
        return {"status": "ok", "timestamp": datetime.now().isoformat()}
        
    except Exception as e:
        logger.error(f"💥 Unexpected webhook error: {e}")
        logger.error(traceback.format_exc())
        error_data = {
            "error": str(e),
            "error_type": type(e).__name__,
            "body_length": len(body) if 'body' in locals() else 0
        }
        monitor.log_webhook_event("unexpected_error", False, error_data)
        return {"status": "error_handled", "error": str(e), "timestamp": datetime.now().isoformat()}

# ★★★ イベントハンドラー（修正版：安全な送信処理）★★★
if LINE_SDK_AVAILABLE and handler:
    @handler.add(MessageEvent, message=TextMessageContent)
    def handle_text_message(event):
        """修正版テキストメッセージ処理（安全な送信処理）"""
        start_time = datetime.now()
        try:
            user_id = event.source.user_id
            message_text = event.message.text
            logger.info(f"📱 Received LINE message from {user_id}: '{message_text[:100]}...'")
           
            # 別スレッドで非同期処理を実行（新しいイベントループを作成）
            def process_in_thread():
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    answer_local = loop.run_until_complete(process_message(message_text, user_id))
                    loop.close()
                    return answer_local
                except Exception as e:
                    logger.error(f"Thread processing error: {e}")
                    return get_emergency_response(message_text)
            
            # 30秒のタイムアウトを設定
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(process_in_thread)
                try:
                    answer = future.result(timeout=30)
                except concurrent.futures.TimeoutError:
                    logger.error("❌ Message processing timeout")
                    answer = "処理に時間がかかっています。しばらくしてから再度お試しください。"
           
            logger.info(f"🤖 Generated answer length: {len(answer)} characters")
           
            # 安全な応答送信
            send_success = send_line_reply_safe(event.reply_token, answer)
            
            processing_time = (datetime.now() - start_time).total_seconds()
            
            if send_success:
                logger.info(f"✅ Sent reply to {user_id} (processing_time: {processing_time:.2f}s)")
                success_data = {
                    "user_id": user_id,
                    "processing_time": processing_time,
                    "message_length": len(message_text),
                    "response_length": len(answer),
                    "message_preview": message_text[:50] + "..." if len(message_text) > 50 else message_text
                }
                monitor.log_webhook_event("message", True, success_data)
            else:
                logger.error(f"❌ Failed to send reply to {user_id}")
                error_data = {
                    "user_id": user_id,
                    "processing_time": processing_time,
                    "message_text": message_text[:50] + "..." if len(message_text) > 50 else message_text,
                    "error": "send_failed"
                }
                monitor.log_webhook_event("message", False, error_data)
           
        except Exception as e:
            processing_time = (datetime.now() - start_time).total_seconds()
            logger.error(f"❌ Error handling text message: {e}")
            logger.error(traceback.format_exc())
            
            error_data = {
                "error": str(e),
                "error_type": type(e).__name__,
                "processing_time": processing_time,
                "user_id": user_id if 'user_id' in locals() else 'unknown',
                "message_text": message_text[:50] + "..." if 'message_text' in locals() and len(message_text) > 50 else message_text if 'message_text' in locals() else 'unknown'
            }
            monitor.log_webhook_event("message", False, error_data)
           
            # 緊急時の応答送信
            try:
                error_message = get_emergency_response(message_text if 'message_text' in locals() else "")
                send_line_reply_safe(event.reply_token, error_message)
                logger.info("🆘 Sent emergency fallback message")
            except Exception as final_error:
                logger.error(f"💥 Final error response failed: {final_error}")

    @handler.add(PostbackEvent)
    def handle_postback(event):
        """包括的Postbackイベント処理（安全な送信処理）"""
        start_time = datetime.now()
        try:
            user_id = event.source.user_id
            postback_data = event.postback.data
            display_text = getattr(event.postback, 'display_text', '')
            logger.info(f"🔙 Postback received from {user_id}: {postback_data}")
            
            params = {}
            try:
                params = dict(param.split('=') for param in postback_data.split('&'))
                logger.info(f"📊 Parsed postback params: {params}")
            except Exception as parse_error:
                logger.error(f"❌ Postback data parsing failed: {parse_error}")
                params = {'action': 'unknown'}
            
            action = params.get('action', 'unknown')
            source = params.get('source', 'richmenu')
            
            try:
                response_text = get_richmenu_response(action, user_id) or f"アクション '{action}' を受信しました。処理中です..."
                
                # 安全な送信処理
                send_success = send_line_reply_safe(event.reply_token, response_text)
                
                processing_time = (datetime.now() - start_time).total_seconds()
                
                if send_success:
                    success_data = {
                        "action": action,
                        "source": source,
                        "user_id": user_id,
                        "processing_time": processing_time,
                        "display_text": display_text,
                        "postback_data": postback_data
                    }
                    monitor.log_webhook_event("postback", True, success_data)
                    logger.info(f"✅ Postback processed successfully: {action} (time: {processing_time:.2f}s)")
                else:
                    logger.error(f"❌ Failed to send postback response for action: {action}")
                    
            except Exception as process_error:
                logger.error(f"❌ Postback processing error: {process_error}")
                # 緊急時の応答
                fallback_text = "申し訳ございません。処理中にエラーが発生しました。再度お試しください。"
                send_line_reply_safe(event.reply_token, fallback_text)
                
                processing_time = (datetime.now() - start_time).total_seconds()
                error_data = {
                    "action": action,
                    "source": source,
                    "error": str(process_error),
                    "error_type": type(process_error).__name__,
                    "processing_time": processing_time,
                    "user_id": user_id,
                    "postback_data": postback_data
                }
                monitor.log_webhook_event("postback", False, error_data)
                
        except Exception as e:
            processing_time = (datetime.now() - start_time).total_seconds()
            logger.error(f"💥 Postback handler error: {e}")
            logger.error(traceback.format_exc())
            error_data = {
                "error": str(e),
                "error_type": type(e).__name__,
                "processing_time": processing_time,
                "user_id": user_id if 'user_id' in locals() else 'unknown'
            }
            monitor.log_webhook_event("postback", False, error_data)

    @handler.add(FollowEvent)
    def handle_follow(event):
        """友達追加時の包括的処理（安全な送信処理）"""
        try:
            user_id = event.source.user_id
            logger.info(f"👤 New follower: {user_id}")
            
            welcome_message = """🎉 友達追加ありがとうございます！

キノエデザインの住まいAIコンシェルジュです。
お客様の理想の住まいづくりをサポートいたします。

🏠 画面下のメニューから各種サービスをご利用いただけます：

🤖 AI相談
住まいに関するご質問にAIがお答えします

📋 資料請求  
総合カタログや施工事例集をお送りします

📍 展示場予約
実際の住まいをご体感いただけます

💰 資金計画
住宅ローンや資金計画をサポート

💬 チャット相談
スタッフと直接チャットでご相談

どうぞお気軽にご利用ください！
素敵な住まいづくりを一緒に始めましょう✨"""

            send_success = send_line_reply_safe(event.reply_token, welcome_message)
            
            if send_success:
                success_data = {
                    "user_id": user_id,
                    "welcome_message_sent": True,
                    "timestamp": datetime.now().isoformat()
                }
                monitor.log_webhook_event("follow", True, success_data)
                logger.info(f"✅ Welcome message sent to new follower: {user_id}")
            else:
                logger.error(f"❌ Failed to send welcome message to: {user_id}")
                
        except Exception as e:
            logger.error(f"❌ Error handling follow event: {e}")
            error_data = {
                "error": str(e),
                "error_type": type(e).__name__,
                "user_id": user_id if 'user_id' in locals() else 'unknown'
            }
            monitor.log_webhook_event("follow", False, error_data)

    @handler.add(UnfollowEvent)
    def handle_unfollow(event):
        """フォロー解除時の処理（デバッグログ強化版）"""
        try:
            user_id = event.source.user_id
            logger.info(f"👋 User unfollowed: {user_id}")
            unfollow_data = {
                "user_id": user_id,
                "timestamp": datetime.now().isoformat()
            }
            monitor.log_webhook_event("unfollow", True, unfollow_data)
        except Exception as e:
            logger.error(f"❌ Error handling unfollow event: {e}")
            error_data = {
                "error": str(e),
                "error_type": type(e).__name__
            }
            monitor.log_webhook_event("unfollow", False, error_data)

# ★★★ 管理・診断エンドポイント ★★★
@router.get("/health")
def get_comprehensive_health():
    """包括的ヘルス状態取得"""
    send_success_rate = monitor.get_send_success_rate()
    
    return {
        "line_bot_status": {
            "configured": bool(line_bot_api and handler),
            "sdk_available": LINE_SDK_AVAILABLE,
            "sdk_version": "3.5.0",
            "credentials_set": bool(LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET),
            "api_client_ready": line_bot_api is not None,
            "handler_ready": handler is not None,
            "token_length": len(LINE_CHANNEL_ACCESS_TOKEN) if LINE_CHANNEL_ACCESS_TOKEN else 0,
            "secret_length": len(LINE_CHANNEL_SECRET) if LINE_CHANNEL_SECRET else 0
        },
        "send_statistics": {
            "success_count": monitor.stats['send_success'],
            "failure_count": monitor.stats['send_failures'],
            "success_rate": send_success_rate,
            "total_attempts": monitor.stats['send_success'] + monitor.stats['send_failures']
        },
        "webhook_statistics": {
            "total_received": monitor.stats['webhook_received'],
            "message_events": monitor.stats['message_events'],
            "postback_events": monitor.stats['postback_events'],
            "follow_events": monitor.stats['follow_events'],
            "error_count": monitor.stats['errors'],
            "error_rate": monitor.get_error_rate()
        },
        "system_info": {
            "timestamp": datetime.now().isoformat(),
            "monitoring_enabled": True,
            "token_normalization_enabled": True
        }
    }

@router.get("/status")
def get_detailed_line_status():
    """詳細なLINE Bot状態確認"""
    return {
        "line_bot_configured": bool(line_bot_api and handler),
        "line_sdk_available": LINE_SDK_AVAILABLE,
        "line_sdk_version": "3.5.0",
        "channel_access_token_set": bool(LINE_CHANNEL_ACCESS_TOKEN),
        "channel_secret_set": bool(LINE_CHANNEL_SECRET),
        "api_client_ready": line_bot_api is not None,
        "handler_ready": handler is not None,
        "webhook_events_processed": monitor.stats['webhook_received'],
        "send_success_rate": monitor.get_send_success_rate(),
        "timestamp": datetime.now().isoformat()
    }

@router.post("/test")
async def test_line_bot():
    """LINE Bot機能のテスト（修正版）"""
    if not line_bot_api:
        logger.error("❌ LINE Bot not configured for testing")
        return {"status": "error", "message": "LINE Bot not configured"}
    try:
        test_message = "テスト"
        test_user_id = "test-user"
        logger.info(f"🧪 Testing LINE Bot with message: '{test_message}'")
        response = await process_message(test_message, test_user_id)
        logger.info(f"✅ Test completed successfully - Response length: {len(response)}")
        
        # トークン正規化テスト
        normalized_token = normalize_line_token(LINE_CHANNEL_ACCESS_TOKEN)
        token_test_result = {
            "original_type": str(type(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))),
            "normalized_length": len(normalized_token),
            "starts_with_bearer": normalized_token.startswith("Bearer "),
            "is_valid_format": len(normalized_token) > 100 and not normalized_token.startswith("Bearer ")
        }
        
        return {
            "status": "success",
            "test_message": test_message,
            "test_response": response[:100] + "..." if len(response) > 100 else response,
            "response_length": len(response),
            "token_test": token_test_result,
            "send_statistics": {
                "success_count": monitor.stats['send_success'],
                "failure_count": monitor.stats['send_failures'],
                "success_rate": monitor.get_send_success_rate()
            },
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }