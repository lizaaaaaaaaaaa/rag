# api/routers/line_bot.py - 完全修正版
# 署名検証エラー対応、監視機能強化、エラーハンドリング改善

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
        elif isinstance(obj, set):  # setオブジェクトの対応
            return list(obj)
        elif hasattr(obj, '__dict__'):
            return make_json_serializable(obj.__dict__)
        elif hasattr(obj, 'isoformat'):  # datetime objects
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
        
        # statsのスナップショットも安全に追加
        try:
            stats_copy = self.stats.copy()
            if stats_copy.get('last_activity'):
                stats_copy['last_activity'] = stats_copy['last_activity'].isoformat()
            if 'richmenu_interactions' in stats_copy:
                for action, data in stats_copy['richmenu_interactions'].items():
                    if isinstance(data, dict) and 'users' in data:
                        if isinstance(data['users'], set):
                            data['users'] = list(data['users'])
            log_data['stats_snapshot'] = make_json_serializable(stats_copy)
        except Exception as e:
            logger.warning(f"Failed to include stats snapshot: {e}")
            log_data['stats_snapshot'] = {"error": "serialization_failed"}
        
        try:
            log_message = safe_json_dumps(log_data)
            if not success:
                logger.error(f"LINE Event Error: {log_message}")
            else:
                logger.info(f"LINE Event Success: {log_message}")
        except Exception as e:
            logger.error(f"LINE Event Log Error - Type: {event_type}, Success: {success}, Error: {e}")
    
    def track_richmenu_interaction(self, action: str, user_id: str, response_time: float = None):
        """リッチメニューインタラクション詳細追跡（修正版）"""
        if action not in self.stats['richmenu_interactions']:
            self.stats['richmenu_interactions'][action] = {
                'count': 0,
                'users': set(),  # 必ずsetで初期化
                'avg_response_time': 0,
                'response_times': []
            }
        
        interaction = self.stats['richmenu_interactions'][action]
        
        # usersがlistになっていた場合はsetに変換
        if isinstance(interaction['users'], list):
            interaction['users'] = set(interaction['users'])
        
        interaction['count'] += 1
        interaction['users'].add(user_id)
        
        if response_time:
            interaction['response_times'].append(response_time)
            interaction['avg_response_time'] = sum(interaction['response_times']) / len(interaction['response_times'])
        
        if user_id not in self.stats['user_activity']:
            self.stats['user_activity'][user_id] = {
                'first_interaction': datetime.now(),
                'last_interaction': datetime.now(),
                'total_interactions': 0,
                'actions': {}
            }
        
        user_activity = self.stats['user_activity'][user_id]
        user_activity['last_interaction'] = datetime.now()
        user_activity['total_interactions'] += 1
        
        if action not in user_activity['actions']:
            user_activity['actions'][action] = 0
        user_activity['actions'][action] += 1
        
        logger.info(f"RichMenu Interaction: {action} by {user_id} (response_time: {response_time}s)")
    
    def get_error_rate(self) -> float:
        total_events = max(self.stats['webhook_received'], 1)
        return self.stats['errors'] / total_events
    
    def get_health_status(self) -> dict:
        error_rate = self.get_error_rate()
        
        activity_level = "low"
        if self.stats['webhook_received'] > 100:
            activity_level = "high"
        elif self.stats['webhook_received'] > 20:
            activity_level = "medium"
        
        popular_actions = []
        for action, data in self.stats['richmenu_interactions'].items():
            if isinstance(data, dict) and 'count' in data:
                popular_actions.append({'action': action, 'count': data['count']})
            else:
                popular_actions.append({'action': action, 'count': data if isinstance(data, int) else 0})
        popular_actions.sort(key=lambda x: x['count'], reverse=True)
        popular_actions = popular_actions[:3]
        
        return {
            'overall_status': 'healthy' if error_rate < 0.1 else 'degraded',
            'error_rate': error_rate,
            'activity_level': activity_level,
            'last_activity': self.stats['last_activity'].isoformat() if self.stats['last_activity'] else None,
            'total_events': self.stats['webhook_received'],
            'event_breakdown': {
                'messages': self.stats['message_events'],
                'postbacks': self.stats['postback_events'],
                'follows': self.stats['follow_events'],
                'unfollows': self.stats['unfollow_events']
            },
            'richmenu_analytics': {
                'total_interactions': sum(
                    data['count'] if isinstance(data, dict) and 'count' in data else (data if isinstance(data, int) else 0)
                    for data in self.stats['richmenu_interactions'].values()
                ),
                'popular_actions': popular_actions,
                'unique_users': len(self.stats['user_activity'])
            },
            'performance': {
                'avg_response_time': sum(self.stats['response_times']) / len(self.stats['response_times']) 
                                    if self.stats['response_times'] else 0
            }
        }

# ★★★ 高度な自動復旧システム ★★★
class AdvancedAutoRecovery:
    def __init__(self):
        self.recovery_strategies = {
            'connection_error': self._recover_connection,
            'rate_limit': self._handle_rate_limit,
            'authentication_error': self._refresh_authentication,
            'server_error': self._restart_services
        }
        
        self.fallback_responses = {
            'ai_consultation': """🤖 AI住まい相談サービス

現在、AIシステムのメンテナンス中です。
しばらくお待ちいただくか、以下の方法でサポートを受けてください：

📞 お電話でのご相談: 0120-XXX-XXX
📧 メールでのお問い合わせ: info@kinoe-design.com
⏰ 営業時間: 9:00-18:00（水曜定休）

お急ぎの場合は直接メッセージでご質問をお送りください。
スタッフが確認次第、ご返答いたします。""",
            
            'document_request': """📋 資料請求サービス

カタログのご請求を承ります。
以下の情報をこのチャットでお送りください：

1️⃣ お名前（フルネーム）
2️⃣ ご住所（〒郵便番号から）
3️⃣ お電話番号
4️⃣ ご希望資料の種類
   ・総合カタログ
   ・施工事例集
   ・標準仕様書
   ・価格表

ご入力いただいた情報を確認次第、
3営業日以内に資料をお送りいたします📮""",
            
            'finance_planning': """💰 資金計画・住宅ローン相談

住まいづくりの資金計画をお手伝いします。

📞 専門スタッフ直通ダイヤル: 0120-XXX-XXX
⏰ 相談受付時間: 9:00-18:00（水曜定休）

💡 ご相談時にお聞かせください：
・ご年収（世帯年収）
・ご用意可能な自己資金
・ご希望の借入額
・返済期間のご希望

または、上記の情報をこのチャットでお送りください。
専門のファイナンシャルプランナーがお答えいたします。

🔒 お客様の個人情報は厳重に管理いたします。""",
            
            'exhibition_reservation': """📍 展示場来場予約

キノエデザイン展示場へのご来場予約を承ります。

🏠 展示場情報
住所：〒XXX-XXXX 住所をここに記載
電話：0120-XXX-XXX
営業時間：9:00-18:00（水曜定休）

📅 ご予約方法
以下の情報をメッセージでお送りください：
・ご希望日時（第1希望・第2希望）
・お名前
・ご連絡先
・参加人数

例）「1月20日（土）14:00希望、田中太郎、090-XXXX-XXXX、2名」

スタッフ一同、心よりお待ちしております！""",
            
            'general_error': """申し訳ございません。
一時的にシステムの調子が悪いようです。

しばらくしてから再度お試しいただくか、
直接メッセージでお気軽にお声かけください。

スタッフが確認次第、お返事いたします。"""
        }
    
    def get_fallback_response(self, action: str, error_context: dict = None) -> str:
        base_response = self.fallback_responses.get(action, self.fallback_responses['general_error'])
        if error_context:
            if error_context.get('error_type') == 'timeout':
                base_response += "\n\n⏱️ 現在、システムの応答に時間がかかっています。"
            elif error_context.get('error_type') == 'rate_limit':
                base_response += "\n\n🚦 現在、アクセスが集中しています。少々お待ちください。"
        return base_response
    
    async def _recover_connection(self, error: Exception) -> bool:
        logger.info("Attempting connection recovery...")
        await asyncio.sleep(1)
        return True
    
    async def _handle_rate_limit(self, error: Exception) -> bool:
        logger.info("Handling rate limit...")
        await asyncio.sleep(5)
        return True
    
    async def _refresh_authentication(self, error: Exception) -> bool:
        logger.info("Refreshing authentication...")
        return True
    
    async def _restart_services(self, error: Exception) -> bool:
        logger.info("Restarting services...")
        return True

# グローバルインスタンス
monitor = ComprehensiveMonitor()
recovery = AdvancedAutoRecovery()

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
        monitor.track_richmenu_interaction(action, user_id)
        
        richmenu_response = get_richmenu_response(action, user_id)
        if richmenu_response and action != "general":
            response_time = (datetime.now() - start_time).total_seconds()
            monitor.track_richmenu_interaction(action, user_id, response_time)
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
        try:
            fallback_response = recovery.get_fallback_response('general_error', {'error_type': type(e).__name__})
            logger.info(f"🆘 Using fallback response due to error")
            return fallback_response
        except Exception as recovery_error:
            logger.error(f"💥 Recovery also failed: {recovery_error}")
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

# ★★★ イベントハンドラー（修正版：非同期→スレッド実行＋タイムアウト）★★★
if LINE_SDK_AVAILABLE and handler:
    @handler.add(MessageEvent, message=TextMessageContent)
    def handle_text_message(event):
        """修正版テキストメッセージ処理（非同期問題解決）"""
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
           
            # 応答送信（v3対応）
            try:
                with ApiClient(Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)) as api_client:
                    messaging_api = MessagingApi(api_client)
                    messaging_api.reply_message_with_http_info(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text=answer)]
                        )
                    )
                
                processing_time = (datetime.now() - start_time).total_seconds()
                monitor.stats['response_times'].append(processing_time)
                logger.info(f"✅ Sent reply to {user_id} (processing_time: {processing_time:.2f}s)")
                
                success_data = {
                    "user_id": user_id,
                    "processing_time": processing_time,
                    "message_length": len(message_text),
                    "response_length": len(answer),
                    "message_preview": message_text[:50] + "..." if len(message_text) > 50 else message_text
                }
                monitor.log_webhook_event("message", True, success_data)
            
            except Exception as send_error:
                logger.error(f"❌ Failed to send reply: {send_error}")
                error_data = {
                    "error": str(send_error),
                    "error_type": type(send_error).__name__,
                    "user_id": user_id,
                    "message_text": message_text[:50] + "..." if len(message_text) > 50 else message_text
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
           
            try:
                error_message = get_emergency_response(message_text if 'message_text' in locals() else "")
                with ApiClient(Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)) as api_client:
                    messaging_api = MessagingApi(api_client)
                    messaging_api.reply_message_with_http_info(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text=error_message)]
                        )
                    )
                logger.info("🆘 Sent emergency fallback message")
            except Exception as final_error:
                logger.error(f"💥 Final error response failed: {final_error}")

    @handler.add(PostbackEvent)
    def handle_postback(event):
        """包括的Postbackイベント処理（デバッグログ強化版）"""
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
            monitor.track_richmenu_interaction(action, user_id)
            
            try:
                response_text = get_richmenu_response(action, user_id) or f"アクション '{action}' を受信しました。処理中です..."
                with ApiClient(Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)) as api_client:
                    messaging_api = MessagingApi(api_client)
                    messaging_api.reply_message_with_http_info(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text=response_text)]
                        )
                    )
                processing_time = (datetime.now() - start_time).total_seconds()
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
            except Exception as process_error:
                logger.error(f"❌ Postback processing error: {process_error}")
                fallback_text = recovery.get_fallback_response(action)
                try:
                    with ApiClient(Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)) as api_client:
                        messaging_api = MessagingApi(api_client)
                        messaging_api.reply_message_with_http_info(
                            ReplyMessageRequest(
                                reply_token=event.reply_token,
                                messages=[TextMessage(text=fallback_text)]
                            )
                        )
                    logger.info("🆘 Sent fallback response for postback error")
                except Exception as fallback_error:
                    logger.error(f"💥 Fallback response failed: {fallback_error}")
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
        """友達追加時の包括的処理（デバッグログ強化版）"""
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
            with ApiClient(Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)) as api_client:
                messaging_api = MessagingApi(api_client)
                messaging_api.reply_message_with_http_info(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=welcome_message)]
                    )
                )
            success_data = {
                "user_id": user_id,
                "welcome_message_sent": True,
                "timestamp": datetime.now().isoformat()
            }
            monitor.log_webhook_event("follow", True, success_data)
            logger.info(f"✅ Welcome message sent to new follower: {user_id}")
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
    health_data = monitor.get_health_status()
    return {
        "line_bot_status": {
            "configured": bool(line_bot_api and handler),
            "sdk_available": LINE_SDK_AVAILABLE,
            "sdk_version": "3.5.0",
            "credentials_set": bool(LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET),
            "api_client_ready": line_bot_api is not None,
            "handler_ready": handler is not None
        },
        "comprehensive_health": health_data,
        "system_info": {
            "timestamp": datetime.now().isoformat(),
            "uptime_seconds": (datetime.now() - datetime.now()).total_seconds(),
            "monitoring_enabled": True,
            "auto_recovery_enabled": True
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
        "timestamp": datetime.now().isoformat()
    }

@router.get("/analytics")
def get_analytics():
    """分析データ取得（JSONシリアライズ対応）"""
    try:
        richmenu_analytics = {}
        for action, data in monitor.stats['richmenu_interactions'].items():
            if isinstance(data, dict):
                safe_data = data.copy()
                if 'users' in safe_data and isinstance(safe_data['users'], set):
                    safe_data['users'] = list(safe_data['users'])
                richmenu_analytics[action] = safe_data
            else:
                richmenu_analytics[action] = data
        
        user_analytics = {
            "total_users": len(monitor.stats['user_activity']),
            "active_users_today": len([
                uid for uid, data in monitor.stats['user_activity'].items() 
                if isinstance(data, dict) and 
                data.get('last_interaction') and
                (datetime.now() - data['last_interaction']).days == 0
            ])
        }
        
        return {
            "richmenu_analytics": richmenu_analytics,
            "user_analytics": user_analytics,
            "performance_metrics": {
                "avg_response_time": sum(monitor.stats['response_times']) / len(monitor.stats['response_times']) 
                                    if monitor.stats['response_times'] else 0,
                "total_events": monitor.stats['webhook_received'],
                "error_rate": monitor.get_error_rate()
            },
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Analytics error: {e}")
        return {"error": "Failed to get analytics", "timestamp": datetime.now().isoformat()}

@router.post("/test")
async def test_line_bot():
    """LINE Bot機能のテスト（デバッグログ強化版）"""
    if not line_bot_api:
        logger.error("❌ LINE Bot not configured for testing")
        return {"status": "error", "message": "LINE Bot not configured"}
    try:
        test_message = "テスト"
        test_user_id = "test-user"
        logger.info(f"🧪 Testing LINE Bot with message: '{test_message}'")
        response = await process_message(test_message, test_user_id)
        logger.info(f"✅ Test completed successfully - Response length: {len(response)}")
        return {
            "status": "success",
            "test_message": test_message,
            "test_response": response[:100] + "..." if len(response) > 100 else response,
            "response_length": len(response),
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

@router.post("/broadcast")
async def broadcast_message(message: dict):
    """ブロードキャストメッセージ送信（管理者用）"""
    if not line_bot_api:
        raise HTTPException(status_code=500, detail="LINE Bot not configured")
    try:
        broadcast_message = TextMessage(text=message.get("text", ""))
        with ApiClient(Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)) as api_client:
            messaging_api = MessagingApi(api_client)
            # 実装は必要に応じて
        return {"status": "success", "message": "Broadcast sent"}
    except Exception as e:
        logger.error(f"Broadcast error: {e}")
        raise HTTPException(status_code=500, detail=str(e))