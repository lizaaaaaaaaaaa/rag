# api/routers/line_bot_ultra_fast.py
# 重複メッセージ完全防止版（資金計画機能統合）

import logging
import os
import re
import json
import asyncio
import traceback
import time
import hashlib
from datetime import datetime, timedelta
from typing import Dict, Optional, Any, List
import concurrent.futures

from fastapi import APIRouter, Request, BackgroundTasks
from fastapi.responses import JSONResponse

# 資金計画機能をインポート
from api.routers.line_bot_financial_planner import (
    FinancialPlanningHandler, 
    is_financial_planning_message,
    handle_financial_message_for_line
)

logger = logging.getLogger(__name__)

# LINE SDK v3 import
try:
    from linebot.v3 import WebhookHandler
    from linebot.v3.exceptions import InvalidSignatureError
    from linebot.v3.messaging import (
        Configuration, ApiClient, MessagingApi, ReplyMessageRequest, PushMessageRequest, TextMessage,
        ApiException
    )
    from linebot.v3.webhooks import MessageEvent, TextMessageContent, PostbackEvent, FollowEvent
    LINE_SDK_AVAILABLE = True
    logger.info("✅ LINE Bot SDK v3 imported successfully")
except ImportError as e:
    logger.error(f"❌ LINE Bot SDK not available: {e}")
    LINE_SDK_AVAILABLE = False
    class WebhookHandler:
        def __init__(self, *args, **kwargs): pass
        def add(self, *args, **kwargs):
            def decorator(func): return func
            return decorator
        def handle(self, *args, **kwargs): pass

router = APIRouter(tags=["line-smart-integrated-financial-no-duplicates"])

# ==============================================================================
# 重複メッセージ防止システム（統合版）
# ==============================================================================
class LineDuplicateMessagePrevention:
    """LINE専用重複メッセージ防止システム"""
    
    def __init__(self):
        self.recent_sends = {}  # {(user_id, message_hash): timestamp}
        self.recent_events = {}  # {(user_id, event_hash): timestamp}  # 🆕 イベント重複防止
        self.duplicate_window = 60  # 60秒以内の重複を防止
        self.event_window = 10  # 10秒以内のイベント重複を防止
        self.cleanup_interval = 300  # 5分毎にクリーンアップ
        self.last_cleanup = time.time()
        self.stats = {
            "message_duplicates_prevented": 0,
            "event_duplicates_prevented": 0,
            "total_send_attempts": 0,
            "successful_sends": 0
        }
        
    def should_send_message(self, user_id: str, message: str) -> bool:
        """メッセージを送信すべきかチェック"""
        self.stats["total_send_attempts"] += 1
        
        # メッセージハッシュ生成（最初の100文字で判定）
        message_preview = message[:100]
        message_hash = hashlib.md5(message_preview.encode()).hexdigest()[:8]
        key = (user_id, message_hash)
        
        current_time = time.time()
        
        # 定期クリーンアップ
        if current_time - self.last_cleanup > self.cleanup_interval:
            self._cleanup_old_records(current_time)
        
        # 重複チェック
        if key in self.recent_sends:
            time_diff = current_time - self.recent_sends[key]
            if time_diff < self.duplicate_window:
                logger.warning(f"🛑 MESSAGE duplicate suppressed: user={user_id}, age={time_diff:.1f}s, hash={message_hash}")
                self.stats["message_duplicates_prevented"] += 1
                return False
        
        # 送信記録
        self.recent_sends[key] = current_time
        self.stats["successful_sends"] += 1
        return True
    
    def should_process_event(self, user_id: str, event_data: str) -> bool:
        """🆕 イベントを処理すべきかチェック（Webhook レベルでの重複防止）"""
        event_hash = hashlib.md5(event_data.encode()).hexdigest()[:8]
        key = (user_id, event_hash)
        
        current_time = time.time()
        
        # イベント重複チェック
        if key in self.recent_events:
            time_diff = current_time - self.recent_events[key]
            if time_diff < self.event_window:
                logger.warning(f"🛑 EVENT duplicate suppressed: user={user_id}, age={time_diff:.1f}s, hash={event_hash}")
                self.stats["event_duplicates_prevented"] += 1
                return False
        
        # イベント記録
        self.recent_events[key] = current_time
        return True
    
    def _cleanup_old_records(self, current_time: float):
        """古い記録をクリーンアップ"""
        # メッセージ記録のクリーンアップ
        message_cutoff = current_time - self.duplicate_window * 2
        old_message_keys = [key for key, timestamp in self.recent_sends.items() if timestamp < message_cutoff]
        
        for key in old_message_keys:
            del self.recent_sends[key]
        
        # イベント記録のクリーンアップ
        event_cutoff = current_time - self.event_window * 2
        old_event_keys = [key for key, timestamp in self.recent_events.items() if timestamp < event_cutoff]
        
        for key in old_event_keys:
            del self.recent_events[key]
        
        self.last_cleanup = current_time
        
        if old_message_keys or old_event_keys:
            logger.info(f"🧹 Cleaned up {len(old_message_keys)} message records, {len(old_event_keys)} event records")
    
    def get_stats(self) -> Dict[str, Any]:
        """重複防止統計取得"""
        return {
            "active_message_records": len(self.recent_sends),
            "active_event_records": len(self.recent_events),
            "message_duplicate_window_seconds": self.duplicate_window,
            "event_duplicate_window_seconds": self.event_window,
            "stats": self.stats.copy()
        }

# ==============================================================================
# LINE統合スマートルーティングシステム（重複防止強化版）
# ==============================================================================
class LineSmartRouterWithDuplicatePrevention:
    """LINE専用スマートルーティングシステム（重複防止強化版）"""
    
    def __init__(self):
        self.routing_stats = {
            "template_responses": 0,
            "rag_responses": 0,
            "financial_responses": 0,
            "fallback_responses": 0,
            "total_requests": 0,
            "processing_times": []
        }
        
        # 資金計画ハンドラー初期化
        self.financial_handler = FinancialPlanningHandler()
        
        # テンプレート即座応答キーワード（資金計画除外）
        self.template_keywords = {
            # リッチメニュー項目（資金計画以外）
            "ai相談": "AI相談",
            "🤖ai相談": "AI相談", 
            "ai住まいサイト": "AI住まいサイト",
            "🌐ai住まいサイト": "AI住まいサイト",
            "aiサイト": "AI住まいサイト",
            "資料請求": "資料請求",
            "📋資料請求": "資料請求",
            "展示場来場予約": "展示場来場予約",
            "📍展示場来場予約": "展示場来場予約",
            "展示場予約": "展示場来場予約",
            "チャット相談": "チャット相談",
            "💬チャット相談": "チャット相談",
            
            # 基本応答
            "こんにちは": "挨拶",
            "はじめまして": "挨拶",
            "よろしく": "挨拶",
            "ありがとう": "お礼",
            "助かり": "お礼"
        }
        
        # 資金計画キーワード（特別処理）
        self.financial_keywords = [
            "資金計画", "💰資金計画", "💰", "ローン計算", "予算診断", "支払い診断",
            "年収", "返済", "借入期間", "家族構成", "負担", "車ローン"
        ]
        
        # RAG処理が必要なキーワード（専門知識）
        self.rag_keywords = [
            "坪単価", "価格", "費用", "金額", "コスト", "値段", "見積り", "料金",
            "仕様", "標準", "設備", "グレード", "オプション", "何が含ま", "含まれる",
            "断熱", "性能", "省エネ", "ZEH", "UA値", "C値", "気密", "光熱費",
            "耐震", "地震", "安全", "構造", "基礎", "工法", "強度", "震災",
            "補助金", "助成金", "支援金", "制度", "控除", "減税", "支援制度",
            "間取り", "プラン", "設計", "レイアウト", "配置", "部屋数",
            "土地", "敷地", "分譲", "宅地", "建築地", "土地探し",
            "建ぺい率", "容積率", "法規", "規制", "基準", "建築基準法"
        ]
        
        # テンプレートを読み込み
        self.templates = self._load_templates()
        
    def _load_templates(self) -> Dict[str, str]:
        """統合テンプレート読み込み（重複防止対応版）"""
        return {
            "AI相談": """🤖 AI住まい相談を開始します！

キノエデザインの住まいAIコンシェルジュです。
住まいに関するご質問をお気軽にどうぞ！

💡 例えば
・坪単価について教えて
・標準仕様はどんな感じ？
・耐震性能について知りたい
・断熱性能はどのくらい？

何でもお聞きください😊

※ご使用の前に、必ず以下の取り扱いをご確認ください。
プライバシーポリシー：https://preview.studio.site/live/EjOQljz1WJ/privacy-policy
利用規約：https://preview.studio.site/live/EjOQljz1WJ/termsofuse/service
Cookie：https://preview.studio.site/live/EjOQljz1WJ/cookie""",

            "AI住まいサイト": """🌐 AI住まいサイトのご案内

キノエデザインの住まい情報サイトをご紹介します。（家づくりの疑問にAIが24時間即回答）

🏠 サイト内容：
・AIチャット相談（資金計画／補助金／間取り など）
・施工写真（実例）
・間取りの考え方・プラン例
・よくある質問（最初に迷う3つのこと ほか）
・保存版デジタル冊子 ZINE（無料ダウンロード）
・LINEで無料相談／来場予約

📱 サイトURL:
https://preview.studio.site/live/EjOQljz1WJ/""",

            "資料請求": """📋 ありがとうございます！こちらからご覧いただけます。

〔資料タイトル〕（PDF）：〔URL〕

よろしければ簡単アンケート（任意）：
・ご計画時期：今すぐ / 3–6か月 / 1年以内 / 未定
・連絡方法（任意）：このLINE / メール / 連絡不要

※必ず以下の取り扱いをご確認ください。
プライバシーポリシー：https://preview.studio.site/live/EjOQljz1WJ/privacy-policy
利用規約：https://preview.studio.site/live/EjOQljz1WJ/termsofuse/service
Cookie：https://preview.studio.site/live/EjOQljz1WJ/cookie""",

            "展示場来場予約": """📍 展示場のご来場予約につきましては、下記URLより必要事項のご入力をお願い申し上げます。

https://preview.studio.site/live/EjOQljz1WJ/reservation

スタッフ一同、心よりお待ちしております！""",

            "チャット相談": """💬 スタッフとのご相談

【対応時間】
営業時間：9:00-18:00

📱 ご相談方法：
・このLINEでの直接相談
・お電話での相談
・展示場での対面相談

営業時間内でしたら迅速にお返事します。
お気軽にお声かけください！""",

            "挨拶": """こんにちは！キノエデザインです✨

住まいづくりのことでしたら何でもお気軽にご相談ください😊

**🎯 人気のご相談内容**
💰 坪単価・価格について
🏠 住宅性能・仕様について  
📋 資料請求・展示場見学
💴 資金計画・住宅ローン

どのようなことを知りたいですか？""",

            "お礼": """どういたしまして😊

他にもご質問がございましたら、お気軽にお聞かせください。

**📞 より詳しい相談をご希望の場合**
・「展示場予約」→専門スタッフが直接対応
・「資料請求」→詳細資料をお送りします

住まいづくりを全力でサポートいたします✨"""
        }
        
    def determine_response_route(self, message_text: str, user_id: str) -> Dict[str, Any]:
        """メッセージに基づく応答ルート決定（重複防止対応版）"""
        start_time = time.time()
        self.routing_stats["total_requests"] += 1
        
        message_lower = message_text.lower().replace(" ", "").replace("　", "")
        
        # 1. 資金計画処理チェック（最優先）
        if (is_financial_planning_message(message_text) or 
            self.financial_handler.state_manager.get_session(user_id)):
            
            self.routing_stats["financial_responses"] += 1
            processing_time = time.time() - start_time
            self.routing_stats["processing_times"].append(processing_time)
            
            return {
                "route": "financial",
                "processing_time": processing_time,
                "reason": "Financial planning session active or initiated"
            }
        
        # 2. テンプレート応答チェック（高速）
        for keyword, template_key in self.template_keywords.items():
            if keyword in message_lower or keyword == message_lower:
                self.routing_stats["template_responses"] += 1
                processing_time = time.time() - start_time
                self.routing_stats["processing_times"].append(processing_time)
                
                return {
                    "route": "template",
                    "template_key": template_key,
                    "response": self.templates.get(template_key, ""),
                    "processing_time": processing_time,
                    "reason": f"Template match: {keyword}"
                }
        
        # 3. RAG処理が必要なキーワードチェック
        rag_matched = []
        for keyword in self.rag_keywords:
            if keyword in message_text:
                rag_matched.append(keyword)
        
        if rag_matched:
            self.routing_stats["rag_responses"] += 1
            processing_time = time.time() - start_time
            self.routing_stats["processing_times"].append(processing_time)
            
            return {
                "route": "rag",
                "rag_keywords": rag_matched,
                "processing_time": processing_time,
                "reason": f"RAG keywords matched: {', '.join(rag_matched[:3])}"
            }
        
        # 4. 質問の複雑さと長さで判定
        question_indicators = ["？", "?", "教えて", "知りたい", "どう", "なぜ", "どこ", "いつ", "いくら"]
        is_question = any(indicator in message_text for indicator in question_indicators)
        
        if is_question and len(message_text) > 15:
            self.routing_stats["rag_responses"] += 1
            processing_time = time.time() - start_time
            self.routing_stats["processing_times"].append(processing_time)
            
            return {
                "route": "rag",
                "rag_keywords": ["complex_question"],
                "processing_time": processing_time,
                "reason": f"Complex question detected (length: {len(message_text)})"
            }
        
        # 5. フォールバック（基本応答）
        self.routing_stats["fallback_responses"] += 1
        processing_time = time.time() - start_time
        self.routing_stats["processing_times"].append(processing_time)
        
        return {
            "route": "fallback",
            "processing_time": processing_time,
            "reason": "No specific pattern matched"
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """統計情報取得（重複防止統計追加）"""
        total = self.routing_stats["total_requests"]
        avg_processing_time = sum(self.routing_stats["processing_times"]) / len(self.routing_stats["processing_times"]) if self.routing_stats["processing_times"] else 0
        
        return {
            "total_requests": total,
            "template_responses": self.routing_stats["template_responses"],
            "rag_responses": self.routing_stats["rag_responses"],
            "financial_responses": self.routing_stats["financial_responses"],
            "fallback_responses": self.routing_stats["fallback_responses"],
            "template_rate": (self.routing_stats["template_responses"] / total * 100) if total > 0 else 0,
            "rag_rate": (self.routing_stats["rag_responses"] / total * 100) if total > 0 else 0,
            "financial_rate": (self.routing_stats["financial_responses"] / total * 100) if total > 0 else 0,
            "fallback_rate": (self.routing_stats["fallback_responses"] / total * 100) if total > 0 else 0,
            "avg_processing_time_ms": avg_processing_time * 1000,
            "financial_integration": True,
            "duplicate_prevention": True,  # 🆕
            "single_handler": True
        }

# ==============================================================================
# RAG処理統合クラス（既存）
# ==============================================================================
class LineRAGIntegration:
    """LINE用RAG処理統合"""
    
    def __init__(self):
        self.rag_cache = {}
        self.rag_available = False
        self._initialize_rag()
    
    def _initialize_rag(self):
        """RAGシステム初期化"""
        try:
            from main import vectorstore, rag_chain_template, llm_instance, is_initialized
            if is_initialized and rag_chain_template:
                self.rag_available = True
                logger.info("✅ RAG integration initialized for LINE")
            else:
                logger.info("ℹ️ RAG not initialized, will use fallback")
        except Exception as e:
            logger.warning(f"⚠️ RAG integration failed: {e}")
    
    async def process_rag_query(self, query: str, user_id: str) -> str:
        """RAG処理実行"""
        if not self.rag_available:
            return self._generate_rag_fallback(query)
        
        # キャッシュチェック
        cache_key = hashlib.md5(f"{query}::{user_id}".encode()).hexdigest()
        if cache_key in self.rag_cache:
            cached_result = self.rag_cache[cache_key]
            if time.time() - cached_result["timestamp"] < 3600:  # 1時間キャッシュ
                logger.info(f"🎯 RAG cache hit for: {query[:30]}...")
                return cached_result["answer"]
        
        try:
            # メインアプリのRAGチェーンを使用
            from main import rag_chain_template
            if rag_chain_template:
                # タイムアウト付きRAG処理
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(self._execute_rag, query, rag_chain_template)
                    try:
                        result = future.result(timeout=8)  # 8秒タイムアウト
                        if result and len(result.strip()) > 10:
                            # キャッシュ保存
                            self.rag_cache[cache_key] = {
                                "answer": result,
                                "timestamp": time.time()
                            }
                            return self._ensure_line_format(result)
                    except concurrent.futures.TimeoutError:
                        logger.warning("⚠️ RAG processing timeout")
            
            return self._generate_rag_fallback(query)
            
        except Exception as e:
            logger.error(f"❌ RAG processing error: {e}")
            return self._generate_rag_fallback(query)
    
    def _execute_rag(self, query: str, rag_chain):
        """RAG実行（同期処理）"""
        result = rag_chain.invoke({"query": query})
        return result.get("result", "")
    
    def _ensure_line_format(self, text: str) -> str:
        """LINE用フォーマット調整"""
        if not text.endswith(('。', '！', '？', '.', '!', '?')):
            text += '。'
        
        # LINE用に長すぎる場合は短縮
        if len(text) > 1500:
            text = text[:1400] + "...\n\n詳しくはお問い合わせください😊"
        
        return text
    
    def _generate_rag_fallback(self, query: str) -> str:
        """RAG処理失敗時のフォールバック"""
        query_lower = query.lower()
        
        if any(keyword in query_lower for keyword in ["坪単価", "価格", "費用", "金額"]):
            return """💰 坪単価についてご案内いたします

🏠 **当社の坪単価目安**
・標準仕様：約70～85万円/坪
・高性能仕様：約85～100万円/坪

✨ **含まれる内容**
・耐震等級3の構造
・長期優良住宅対応
・高断熱・高気密仕様
・標準設備一式

詳細なお見積りは「展示場予約」でご相談ください😊"""
        
        elif any(keyword in query_lower for keyword in ["断熱", "性能", "省エネ"]):
            return """🌡️ 断熱性能についてご案内いたします

**断熱等級**
・断熱等級4以上（ZEH基準対応）
・UA値：0.6以下
・C値：1.0以下（高気密）

**快適性**
・夏涼しく、冬暖かい
・光熱費の削減効果
・一年中快適な室温

詳しくは展示場で体感してください✨
「展示場予約」でお申し込みいただけます！"""
        
        else:
            return """ご質問ありがとうございます😊

より詳しい情報をお答えするため、専門スタッフがご対応いたします。

**📞 すぐに相談したい場合**
「展示場予約」で直接ご相談いただけます

**📄 詳しい資料が欲しい場合**  
「資料請求」で専門資料をお送りします

どちらがよろしいでしょうか？"""

# ==============================================================================
# LINE Bot設定と初期化（既存）
# ==============================================================================
def get_line_credentials_safe():
    """LINE認証情報を安全に取得"""
    access_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    channel_secret = os.getenv("LINE_CHANNEL_SECRET")
    
    # Secret Manager対応
    if not access_token or not channel_secret:
        try:
            from google.cloud import secretmanager
            client = secretmanager.SecretManagerServiceClient()
            project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "rag-cloud-project")
            
            if not access_token:
                name = f"projects/{project_id}/secrets/LINE_CHANNEL_ACCESS_TOKEN/versions/latest"
                resp = client.access_secret_version(request={"name": name})
                access_token = resp.payload.data.decode("UTF-8")
            
            if not channel_secret:
                name = f"projects/{project_id}/secrets/LINE_CHANNEL_SECRET/versions/latest"
                resp = client.access_secret_version(request={"name": name})
                channel_secret = resp.payload.data.decode("UTF-8")
                
        except Exception as e:
            logger.warning(f"Secret Manager access failed: {e}")
    
    return access_token, channel_secret

def normalize_line_token(token) -> str:
    """LINE トークン正規化"""
    if not token:
        return ""
    
    token_str = str(token)
    token_str = token_str.replace('\r', '').replace('\n', '').replace('\t', '').strip()
    
    if token_str.lower().startswith("bearer "):
        token_str = token_str[7:].strip()
    
    if token_str.startswith("b'") and token_str.endswith("'"):
        token_str = token_str[2:-1]
    
    token_str = token_str.replace('"', '').replace("'", "")
    return ''.join(token_str.split())

# 初期化
LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET = get_line_credentials_safe()
line_bot_api = None
handler = None

# グローバルインスタンス（重複防止強化版）
smart_router = LineSmartRouterWithDuplicatePrevention()
rag_integration = LineRAGIntegration()
duplicate_prevention = LineDuplicateMessagePrevention()  # 🆕

if LINE_SDK_AVAILABLE and LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET:
    try:
        normalized_token = normalize_line_token(LINE_CHANNEL_ACCESS_TOKEN)
        normalized_secret = normalize_line_token(LINE_CHANNEL_SECRET)
        
        if normalized_token and normalized_secret:
            configuration = Configuration(access_token=normalized_token)
            handler = WebhookHandler(normalized_secret)
            
            with ApiClient(configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
            
            logger.info("✅ LINE Smart Integrated Bot with Duplicate Prevention initialized")
        else:
            raise ValueError("Empty normalized credentials")
            
    except Exception as e:
        logger.error(f"❌ LINE Bot initialization failed: {e}")
        line_bot_api, handler = None, None

# ==============================================================================
# 安全送信関数（重複防止強化版）
# ==============================================================================
def send_line_message_safe(reply_token: str, user_id: str, message: str) -> bool:
    """安全なLINE送信（重複防止機能付き）"""
    if not line_bot_api:
        logger.error("❌ LINE Bot API not initialized")
        return False
    
    # 🆕 重複防止チェック
    if not duplicate_prevention.should_send_message(user_id, message):
        logger.info(f"🛑 Duplicate message prevented for user: {user_id}")
        return True  # 重複防止されたが「成功」として扱う
    
    try:
        normalized_token = normalize_line_token(LINE_CHANNEL_ACCESS_TOKEN)
        if not normalized_token:
            logger.error("❌ Failed to normalize token")
            return False
        
        configuration = Configuration(access_token=normalized_token)
        with ApiClient(configuration) as api_client:
            messaging_api = MessagingApi(api_client)
            
            # まずReply APIを試行
            try:
                messaging_api.reply_message_with_http_info(
                    ReplyMessageRequest(
                        reply_token=reply_token,
                        messages=[TextMessage(text=message)]
                    )
                )
                logger.info(f"✅ Reply sent: {len(message)} chars")
                return True
                
            except ApiException as reply_error:
                # Reply失効時はPush APIにフォールバック
                if "Invalid reply token" in str(reply_error) or getattr(reply_error, "status", None) == 400:
                    logger.warning(f"⚠️ Reply token expired, using Push API fallback")
                    
                    try:
                        messaging_api.push_message_with_http_info(
                            PushMessageRequest(
                                to=user_id,
                                messages=[TextMessage(text=message)]
                            )
                        )
                        logger.info(f"✅ Push message sent as fallback: {len(message)} chars")
                        return True
                    except Exception as push_error:
                        logger.error(f"❌ Push API also failed: {push_error}")
                        return False
                else:
                    logger.error(f"❌ Reply API error: {reply_error}")
                    return False
        
    except Exception as e:
        logger.error(f"❌ Line message sending failed: {e}")
        return False

# ==============================================================================
# Webhook エンドポイント（重複防止強化版）
# ==============================================================================
@router.post("/webhook")
async def smart_integrated_webhook_with_duplicate_prevention(request: Request, background_tasks: BackgroundTasks):
    """重複防止機能付きスマート統合Webhook"""
    logger.info("🚀 LINE Smart Integrated Webhook with Duplicate Prevention called")
    
    if not line_bot_api or not handler:
        logger.error("❌ LINE Bot not configured properly")
        return {"status": "error", "message": "LINE Bot not configured"}
    
    try:
        body = await request.body()
        signature = request.headers.get("X-Line-Signature", "")
        
        if not signature:
            logger.error("❌ Missing X-Line-Signature header")
            return {"status": "error", "message": "Missing signature"}
        
        body_text = body.decode("utf-8")
        logger.info(f"📨 Duplicate prevention webhook processing: {body_text[:200]}...")
        
        handler.handle(body_text, signature)
        
        logger.info("✅ Duplicate prevention webhook processed successfully")
        return {"status": "ok", "timestamp": datetime.now().isoformat()}
        
    except InvalidSignatureError as sig_error:
        logger.error(f"❌ Invalid signature: {sig_error}")
        return {"status": "signature_error"}
    except Exception as e:
        logger.error(f"💥 Smart integrated webhook with duplicate prevention error: {e}")
        logger.error(traceback.format_exc())
        return {"status": "error", "error": str(e)}

# ==============================================================================
# イベントハンドラ（重複防止強化版）
# ==============================================================================
if LINE_SDK_AVAILABLE and handler:
    
    @handler.add(FollowEvent)
    def handle_follow_with_duplicate_prevention(event):
        """フォローハンドラ（重複防止強化版）"""
        start_time = time.time()
        try:
            user_id = event.source.user_id
            reply_token = event.reply_token
            
            # 🆕 イベント重複防止チェック
            event_data = f"follow_{user_id}_{reply_token}"
            if not duplicate_prevention.should_process_event(user_id, event_data):
                logger.info(f"🛑 Follow event duplicate prevented for user: {user_id}")
                return
            
            logger.info(f"👤 New follower (duplicate prevention): {user_id}")
            
            greeting_message = """こんにちは！キノエデザインです✨
この度は友だち追加ありがとうございます。

**🎯 目的のボタンをタップ👇**
🤖AI相談 / 📍来場予約 / 📄資料請求 / 💴資金計画 / 🌐サイト / 💬チャット

**⚡ 応答について**
・AIは24時間対応
・資金計画は段階的に診断
・スタッフは営業日に対応
・営業時間：9:00-18:00

**🔒 プライバシー**
取扱い：https://preview.studio.site/live/EjOQljz1WJ/privacy-policy

住まいのことなら何でもお気軽にご相談ください😊"""
            
            success = send_line_message_safe(reply_token, user_id, greeting_message)
            
            duration = (time.time() - start_time) * 1000
            logger.info(f"✅ Greeting with duplicate prevention sent: {duration:.1f}ms, success: {success}")
            
        except Exception as e:
            logger.error(f"❌ Follow handler with duplicate prevention error: {e}")
            logger.error(traceback.format_exc())
    
    @handler.add(MessageEvent, message=TextMessageContent)
    def handle_message_with_duplicate_prevention(event):
        """メッセージハンドラ（重複防止強化版・単一応答保証）"""
        start_time = time.time()
        
        try:
            user_id = event.source.user_id
            message_text = event.message.text
            reply_token = event.reply_token
            
            # 🆕 イベント重複防止チェック
            event_data = f"message_{user_id}_{message_text[:50]}_{reply_token}"
            if not duplicate_prevention.should_process_event(user_id, event_data):
                logger.info(f"🛑 Message event duplicate prevented for user: {user_id}")
                return
            
            logger.info(f"📱 Processing with duplicate prevention: '{message_text[:30]}...' from user: {user_id}")
            
            # スマートルーティング実行
            routing_result = smart_router.determine_response_route(message_text, user_id)
            route = routing_result["route"]
            
            logger.info(f"🧠 Route selected with duplicate prevention: {route} - {routing_result['reason']}")
            
            # ルート別処理
            if route == "financial":
                # 資金計画処理
                logger.info(f"💰 Processing financial planning for user: {user_id}")
                response_text = handle_financial_message_for_line(user_id, message_text)
                success = send_line_message_safe(reply_token, user_id, response_text)
                
                duration = (time.time() - start_time) * 1000
                logger.info(f"💰 Financial response with dup prevention: {duration:.1f}ms, success: {success}")
                
            elif route == "template":
                # テンプレート即座応答
                response_text = routing_result["response"]
                success = send_line_message_safe(reply_token, user_id, response_text)
                
                duration = (time.time() - start_time) * 1000
                logger.info(f"⚡ Template response with dup prevention: {duration:.1f}ms, success: {success}")
                
            elif route == "rag":
                # RAG処理（非同期実行）
                def process_rag():
                    try:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        result = loop.run_until_complete(
                            rag_integration.process_rag_query(message_text, user_id)
                        )
                        loop.close()
                        return result
                    except Exception as e:
                        logger.error(f"RAG processing error: {e}")
                        return smart_router.templates.get("挨拶", "申し訳ございません。")
                
                # タイムアウト付きRAG実行
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(process_rag)
                    try:
                        response_text = future.result(timeout=10)  # 10秒タイムアウト
                    except concurrent.futures.TimeoutError:
                        logger.error("❌ RAG processing timeout")
                        response_text = """処理に時間がかかっています。

もう一度お試しいただくか、「展示場予約」で直接ご相談ください😊"""
                
                success = send_line_message_safe(reply_token, user_id, response_text)
                
                duration = (time.time() - start_time) * 1000
                logger.info(f"🤖 RAG response with dup prevention: {duration:.1f}ms, success: {success}")
                
            else:
                # フォールバック応答
                response_text = smart_router.templates.get("挨拶", """ご質問ありがとうございます😊

住まいづくりについて、どのようなことをお知りになりたいでしょうか？

メニューからお選びいただくか、具体的にお聞かせください✨""")
                
                success = send_line_message_safe(reply_token, user_id, response_text)
                
                duration = (time.time() - start_time) * 1000
                logger.info(f"🔄 Fallback response with dup prevention: {duration:.1f}ms, success: {success}")
            
            # 統計更新
            total_duration = (time.time() - start_time) * 1000
            logger.info(f"✅ Message with duplicate prevention processed: {total_duration:.1f}ms, route: {route}")
            
        except Exception as e:
            logger.error(f"❌ Message handler with duplicate prevention error: {e}")
            logger.error(traceback.format_exc())
            try:
                emergency = """申し訳ございません。一時的にシステムの不具合が発生しています。

しばらくしてから再度お試しください😊"""
                send_line_message_safe(event.reply_token, event.source.user_id, emergency)
                logger.info("🆘 Emergency response sent")
            except Exception as final_error:
                logger.error(f"❌ Emergency response failed: {final_error}")

    @handler.add(PostbackEvent)
    def handle_postback_with_duplicate_prevention(event):
        """Postbackハンドラ（重複防止強化版）"""
        try:
            user_id = event.source.user_id
            reply_token = event.reply_token
            postback_data = event.postback.data or ""
            
            # 🆕 イベント重複防止チェック
            event_data = f"postback_{user_id}_{postback_data}_{reply_token}"
            if not duplicate_prevention.should_process_event(user_id, event_data):
                logger.info(f"🛑 Postback event duplicate prevented for user: {user_id}")
                return
            
            logger.info(f"🔙 Postback with duplicate prevention from {user_id}: {postback_data}")
            
            # 資金計画のPostbackをチェック
            if "financial_plan" in postback_data or "資金計画" in postback_data:
                response_text = handle_financial_message_for_line(user_id, "💰 資金計画")
            elif "action=" in postback_data:
                action_value = ""
                for part in postback_data.split("&"):
                    if part.startswith("action="):
                        action_value = part.split("=", 1)[1]
                        break
                
                if action_value == "資金計画":
                    response_text = handle_financial_message_for_line(user_id, "💰 資金計画")
                else:
                    response_text = smart_router.templates.get(action_value, "ご利用ありがとうございます。")
            else:
                response_text = "メニューからお選びください。"
            
            success = send_line_message_safe(reply_token, user_id, response_text)
            logger.info(f"✅ Postback with duplicate prevention processed: success={success}")
            
        except Exception as e:
            logger.error(f"💥 Postback handler with duplicate prevention error: {e}")
            logger.error(traceback.format_exc())

# ==============================================================================
# 重複防止専用エンドポイント（新規追加）
# ==============================================================================
@router.get("/duplicate-prevention-stats")
def get_line_duplicate_prevention_stats():
    """LINE重複防止統計取得"""
    duplicate_stats = duplicate_prevention.get_stats()
    routing_stats = smart_router.get_stats()
    
    return {
        "duplicate_prevention": duplicate_stats,
        "routing_stats": routing_stats,
        "effectiveness": {
            "message_duplicates_prevented": duplicate_stats["stats"]["message_duplicates_prevented"],
            "event_duplicates_prevented": duplicate_stats["stats"]["event_duplicates_prevented"],
            "successful_sends": duplicate_stats["stats"]["successful_sends"],
            "total_send_attempts": duplicate_stats["stats"]["total_send_attempts"],
            "success_rate": (duplicate_stats["stats"]["successful_sends"] / duplicate_stats["stats"]["total_send_attempts"] * 100) if duplicate_stats["stats"]["total_send_attempts"] > 0 else 0
        },
        "timestamp": datetime.now().isoformat()
    }

@router.post("/clear-duplicate-prevention")
def clear_line_duplicate_prevention():
    """LINE重複防止キャッシュクリア"""
    old_message_count = len(duplicate_prevention.recent_sends)
    old_event_count = len(duplicate_prevention.recent_events)
    
    duplicate_prevention.recent_sends.clear()
    duplicate_prevention.recent_events.clear()
    
    return {
        "status": "cleared",
        "cleared_message_records": old_message_count,
        "cleared_event_records": old_event_count,
        "timestamp": datetime.now().isoformat()
    }

# ==============================================================================
# 既存のエンドポイント（資金計画・パフォーマンス・デバッグ）
# ==============================================================================
@router.get("/financial-sessions")
def get_financial_sessions():
    """アクティブな資金計画セッション一覧"""
    sessions = []
    for user_id, session in smart_router.financial_handler.state_manager.user_states.items():
        sessions.append({
            "user_id": user_id,
            "completion_rate": session.get_completion_rate(),
            "missing_fields": session.get_missing_fields(),
            "created_at": session.created_at.isoformat(),
            "data": session.to_dict()
        })
    
    return {
        "active_sessions": len(sessions),
        "sessions": sessions,
        "duplicate_prevention_active": True,
        "timestamp": datetime.now().isoformat()
    }

@router.get("/performance")
def get_smart_performance_with_duplicate_prevention():
    """パフォーマンス統計（重複防止機能付き）"""
    stats = smart_router.get_stats()
    duplicate_stats = duplicate_prevention.get_stats()
    active_sessions = len(smart_router.financial_handler.state_manager.user_states)
    
    return {
        "line_smart_integrated_duplicate_prevention_stats": stats,
        "duplicate_prevention_stats": duplicate_stats,
        "financial_planning": {
            "active_sessions": active_sessions,
            "session_timeout_hours": 2,
            "features": [
                "Step-by-step Input Collection",
                "Real-time Input Validation", 
                "Intelligent Loan Calculation",
                "Risk Assessment",
                "Session State Management",
                "Auto Session Cleanup"
            ]
        },
        "system_info": {
            "line_sdk_available": LINE_SDK_AVAILABLE,
            "line_bot_configured": line_bot_api is not None,
            "rag_integration_available": rag_integration.rag_available,
            "financial_planning_enabled": True,
            "duplicate_prevention_enabled": True,  # 🆕
            "single_handler": True
        },
        "features": [
            "🚫 Duplicate Message Prevention (Message + Event Level)",
            "🎯 Single Handler Processing (No Handler Conflicts)",
            "⚡ Smart Route Selection (Template/RAG/Financial/Fallback)",
            "💰 Financial Planning with State Management",
            "🔧 Template Instant Response (< 200ms)",
            "🤖 RAG Integration with Timeout",
            "🧮 Financial Calculation Engine",
            "🛡️ Reply Token Expiry Protection",
            "📤 Push API Automatic Fallback",
            "📱 LINE-Specific Response Formatting",
            "💾 Response Caching"
        ],
        "performance_targets": {
            "template_response_time": "< 200ms",
            "rag_response_time": "< 10s",
            "financial_response_time": "< 1s",
            "duplicate_messages": "0 (prevented)",
            "success_rate": "> 99%"
        },
        "duplicate_prevention_effectiveness": {
            "message_prevention_rate": f"{(duplicate_stats['stats']['message_duplicates_prevented'] / max(duplicate_stats['stats']['total_send_attempts'], 1) * 100):.1f}%",
            "event_prevention_rate": f"Active",
            "overall_success_rate": f"{(duplicate_stats['stats']['successful_sends'] / max(duplicate_stats['stats']['total_send_attempts'], 1) * 100):.1f}%"
        },
        "timestamp": datetime.now().isoformat()
    }

@router.get("/debug")
def smart_debug_info_with_duplicate_prevention():
    """デバッグ情報（重複防止機能付き）"""
    duplicate_stats = duplicate_prevention.get_stats()
    
    return {
        "line_sdk_available": LINE_SDK_AVAILABLE,
        "line_bot_api_initialized": line_bot_api is not None,
        "handler_initialized": handler is not None,
        "smart_router": {
            "available_templates": len(smart_router.templates),
            "template_keywords": len(smart_router.template_keywords),
            "rag_keywords": len(smart_router.rag_keywords),
            "financial_keywords": len(smart_router.financial_keywords),
            "single_handler": True,
            "duplicate_prevention": True
        },
        "rag_integration": {
            "available": rag_integration.rag_available,
            "cache_entries": len(rag_integration.rag_cache)
        },
        "financial_planning": {
            "handler_initialized": True,
            "active_sessions": len(smart_router.financial_handler.state_manager.user_states),
            "calculation_engine": "active",
            "input_parser": "active",
            "state_manager": "active"
        },
        "duplicate_prevention": {  # 🆕
            "enabled": True,
            "stats": duplicate_stats["stats"],
            "active_records": {
                "message_records": duplicate_stats["active_message_records"],
                "event_records": duplicate_stats["active_event_records"]
            },
            "window_settings": {
                "message_window_seconds": duplicate_stats["message_duplicate_window_seconds"],
                "event_window_seconds": duplicate_stats["event_duplicate_window_seconds"]
            }
        },
        "credentials_set": {
            "access_token_set": bool(LINE_CHANNEL_ACCESS_TOKEN),
            "channel_secret_set": bool(LINE_CHANNEL_SECRET)
        },
        "fixes_applied": [
            "🚫 Duplicate message prevention (message + event level)",
            "🎯 Single webhook handler (no handler conflicts)",
            "⚡ Smart routing integration",
            "💰 Financial planning state management",
            "🤖 RAG processing with timeout",
            "📱 Template instant response",
            "🛡️ Reply token expiry handling",
            "🔄 Error recovery with fallback"
        ],
        "timestamp": datetime.now().isoformat()
    }

@router.get("/health")
def smart_health_check_with_duplicate_prevention():
    """ヘルスチェック（重複防止機能付き）"""
    stats = smart_router.get_stats()
    duplicate_stats = duplicate_prevention.get_stats()
    active_sessions = len(smart_router.financial_handler.state_manager.user_states)
    
    health_status = {
        "status": "healthy" if LINE_SDK_AVAILABLE and line_bot_api else "degraded",
        "components": {
            "line_sdk": "ok" if LINE_SDK_AVAILABLE else "error",
            "line_bot_api": "ok" if line_bot_api else "error",
            "handler": "ok" if handler else "error",
            "smart_router": "ok",
            "rag_integration": "ok" if rag_integration.rag_available else "available_fallback",
            "financial_planning": "ok",
            "duplicate_prevention": "ok",  # 🆕
            "credentials": "ok" if LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET else "error"
        },
        "metrics": stats,
        "duplicate_prevention": duplicate_stats,
        "financial_planning": {
            "active_sessions": active_sessions,
            "calculation_engine": "operational",
            "state_management": "operational"
        },
        "duplicate_prevention_summary": {
            "message_duplicates_prevented": duplicate_stats["stats"]["message_duplicates_prevented"],
            "event_duplicates_prevented": duplicate_stats["stats"]["event_duplicates_prevented"],
            "success_rate": f"{(duplicate_stats['stats']['successful_sends'] / max(duplicate_stats['stats']['total_send_attempts'], 1) * 100):.1f}%"
        },
        "single_handler": True,
        "new_features": [
            "Duplicate Message Prevention",
            "Event Duplicate Prevention",
            "Financial Planning Integration"
        ],
        "timestamp": datetime.now().isoformat()
    }
    
    return health_status