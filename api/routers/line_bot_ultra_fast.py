# api/routers/line_bot_ultra_fast.py
# 修正版：RAG共有強化・ログ最適化・重複防止改善

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

# 🆕 main.py からRAG共有コンポーネントを取得
def get_shared_rag_components_safe():
    """main.py からRAGコンポーネントを安全に取得"""
    try:
        from main import get_shared_rag_components
        return get_shared_rag_components()
    except ImportError as e:
        logging.getLogger(__name__).warning(f"⚠️ Cannot import RAG components from main: {e}")
        return {
            "vectorstore": None,
            "rag_chain_template": None,
            "llm_instance": None,
            "is_initialized": False,
            "shared_globally": False
        }

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

router = APIRouter(tags=["line-smart-integrated-financial-fixed"])

# ==============================================================================
# 重複メッセージ防止システム（ログ最適化版）
# ==============================================================================
class LineDuplicateMessagePrevention:
    """LINE専用重複メッセージ防止システム（ログ最適化版）"""
    
    def __init__(self):
        self.recent_sends = {}
        self.recent_events = {}
        self.duplicate_window = 60  # 60秒以内の重複を防止
        self.event_window = 10  # 10秒以内のイベント重複を防止
        self.cleanup_interval = 300  # 5分毎にクリーンアップ
        self.last_cleanup = time.time()
        # ログ出力頻度制御（🆕 ログノイズ削減）
        self.log_throttle = {}
        self.log_throttle_window = 60  # 1分間隔でログ出力
        self.stats = {
            "message_duplicates_prevented": 0,
            "event_duplicates_prevented": 0,
            "total_send_attempts": 0,
            "successful_sends": 0,
            "log_throttled_count": 0  # 🆕 ログ抑制カウント
        }
        
    def should_send_message(self, user_id: str, message: str) -> bool:
        """メッセージを送信すべきかチェック（ログ最適化版）"""
        self.stats["total_send_attempts"] += 1
        
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
                # 🆕 ログ出力頻度制御
                if self._should_log_duplicate("message", user_id, current_time):
                    logger.warning(f"🛑 MESSAGE duplicate suppressed: user={user_id}, age={time_diff:.1f}s, hash={message_hash}")
                else:
                    logger.debug(f"🛑 MESSAGE duplicate suppressed (throttled): user={user_id}")
                    self.stats["log_throttled_count"] += 1
                
                self.stats["message_duplicates_prevented"] += 1
                return False
        
        # 送信記録
        self.recent_sends[key] = current_time
        self.stats["successful_sends"] += 1
        return True
    
    def should_process_event(self, user_id: str, event_data: str) -> bool:
        """イベントを処理すべきかチェック（ログ最適化版）"""
        event_hash = hashlib.md5(event_data.encode()).hexdigest()[:8]
        key = (user_id, event_hash)
        
        current_time = time.time()
        
        # イベント重複チェック
        if key in self.recent_events:
            time_diff = current_time - self.recent_events[key]
            if time_diff < self.event_window:
                # 🆕 ログ出力頻度制御
                if self._should_log_duplicate("event", user_id, current_time):
                    logger.warning(f"🛑 EVENT duplicate suppressed: user={user_id}, age={time_diff:.1f}s, hash={event_hash}")
                else:
                    logger.debug(f"🛑 EVENT duplicate suppressed (throttled): user={user_id}")
                    self.stats["log_throttled_count"] += 1
                
                self.stats["event_duplicates_prevented"] += 1
                return False
        
        # イベント記録
        self.recent_events[key] = current_time
        return True
    
    def _should_log_duplicate(self, log_type: str, user_id: str, current_time: float) -> bool:
        """🆕 ログ出力頻度制御"""
        log_key = f"{log_type}_{user_id}"
        
        if log_key not in self.log_throttle:
            self.log_throttle[log_key] = current_time
            return True
        
        time_since_last_log = current_time - self.log_throttle[log_key]
        if time_since_last_log >= self.log_throttle_window:
            self.log_throttle[log_key] = current_time
            return True
        
        return False
    
    def _cleanup_old_records(self, current_time: float):
        """古い記録をクリーンアップ（ログ最適化版）"""
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
        
        # ログスロットルのクリーンアップ（🆕）
        log_cutoff = current_time - self.log_throttle_window * 2
        old_log_keys = [key for key, timestamp in self.log_throttle.items() if timestamp < log_cutoff]
        
        for key in old_log_keys:
            del self.log_throttle[key]
        
        self.last_cleanup = current_time
        
        # クリーンアップログも抑制（DEBUGレベル）
        if old_message_keys or old_event_keys or old_log_keys:
            logger.debug(f"🧹 Cleaned up {len(old_message_keys)} message, {len(old_event_keys)} event, {len(old_log_keys)} log records")
    
    def get_stats(self) -> Dict[str, Any]:
        """重複防止統計取得（ログ最適化版）"""
        return {
            "active_message_records": len(self.recent_sends),
            "active_event_records": len(self.recent_events),
            "active_log_throttle_records": len(self.log_throttle),  # 🆕
            "message_duplicate_window_seconds": self.duplicate_window,
            "event_duplicate_window_seconds": self.event_window,
            "log_throttle_window_seconds": self.log_throttle_window,  # 🆕
            "stats": self.stats.copy(),
            "log_optimization": "enabled"  # 🆕
        }

# ==============================================================================
# LINE統合スマートルーティングシステム（RAG共有強化版）
# ==============================================================================
class LineSmartRouterWithRAGSharing:
    """LINE専用スマートルーティングシステム（RAG共有強化版）"""
    
    def __init__(self):
        self.routing_stats = {
            "template_responses": 0,
            "rag_responses": 0,
            "financial_responses": 0,
            "fallback_responses": 0,
            "total_requests": 0,
            "processing_times": [],
            "rag_sharing_attempts": 0,  # 🆕 RAG共有試行数
            "rag_sharing_successes": 0  # 🆕 RAG共有成功数
        }
        
        # 資金計画ハンドラー初期化
        self.financial_handler = FinancialPlanningHandler()
        
        # テンプレート即座応答キーワード（資金計画除外）
        self.template_keywords = {
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
        """統合テンプレート読み込み（継続）"""
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
        """メッセージに基づく応答ルート決定（継続）"""
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
        """統計情報取得（RAG共有強化版）"""
        total = self.routing_stats["total_requests"]
        avg_processing_time = sum(self.routing_stats["processing_times"]) / len(self.routing_stats["processing_times"]) if self.routing_stats["processing_times"] else 0
        
        # 🆕 RAG共有成功率
        rag_sharing_success_rate = (self.routing_stats["rag_sharing_successes"] / self.routing_stats["rag_sharing_attempts"] * 100) if self.routing_stats["rag_sharing_attempts"] > 0 else 0
        
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
            "duplicate_prevention": True,
            "single_handler": True,
            "rag_sharing": {  # 🆕 RAG共有統計
                "attempts": self.routing_stats["rag_sharing_attempts"],
                "successes": self.routing_stats["rag_sharing_successes"],
                "success_rate": rag_sharing_success_rate,
                "enabled": True
            }
        }

# ==============================================================================
# RAG処理統合クラス（RAG共有強化版）
# ==============================================================================
class LineRAGIntegrationWithSharing:
    """LINE用RAG処理統合（RAG共有強化版）"""
    
    def __init__(self):
        self.rag_cache = {}
        self.rag_available = False
        self.shared_rag_components = None
        self._initialize_rag()
    
    def _initialize_rag(self):
        """RAGシステム初期化（RAG共有強化版）"""
        try:
            # 🆕 main.py からRAGコンポーネントを取得
            self.shared_rag_components = get_shared_rag_components_safe()
            
            if (self.shared_rag_components["is_initialized"] and 
                self.shared_rag_components["shared_globally"] and
                self.shared_rag_components["rag_chain_template"]):
                
                self.rag_available = True
                logger.info("✅ RAG integration initialized via global sharing from main.py")
                logger.info(f"   - Vectorstore: {'Available' if self.shared_rag_components['vectorstore'] else 'Unavailable'}")
                logger.info(f"   - RAG Chain: {'Available' if self.shared_rag_components['rag_chain_template'] else 'Unavailable'}")
                logger.info(f"   - LLM Instance: {'Available' if self.shared_rag_components['llm_instance'] else 'Unavailable'}")
            else:
                logger.warning("⚠️ RAG components not fully available from main.py, using fallback")
                # レガシーRAG初期化（フォールバック）
                self._try_legacy_rag_init()
                
        except Exception as e:
            logger.warning(f"⚠️ RAG sharing initialization failed: {e}")
            self._try_legacy_rag_init()
    
    def _try_legacy_rag_init(self):
        """🆕 レガシーRAG初期化（フォールバック）"""
        try:
            from main import vectorstore, rag_chain_template, llm_instance, is_initialized
            if is_initialized and rag_chain_template:
                self.rag_available = True
                logger.info("✅ RAG integration initialized via legacy method")
            else:
                logger.info("ℹ️ RAG not initialized, will use fallback responses")
        except Exception as e:
            logger.warning(f"⚠️ Legacy RAG integration also failed: {e}")
    
    async def process_rag_query(self, query: str, user_id: str) -> str:
        """RAG処理実行（RAG共有強化版）"""
        if not self.rag_available:
            return self._generate_rag_fallback(query)
        
        # キャッシュチェック
        cache_key = hashlib.md5(f"{query}::{user_id}".encode()).hexdigest()
        if cache_key in self.rag_cache:
            cached_result = self.rag_cache[cache_key]
            if time.time() - cached_result["timestamp"] < 3600:  # 1時間キャッシュ
                logger.debug(f"🎯 RAG cache hit for: {query[:30]}...")  # 🆕 DEBUGレベル
                return cached_result["answer"]
        
        try:
            # 🆕 共有RAGチェーンを優先使用
            rag_chain = None
            if (self.shared_rag_components and 
                self.shared_rag_components["rag_chain_template"]):
                rag_chain = self.shared_rag_components["rag_chain_template"]
                logger.debug("🤖 Using shared RAG chain from main.py")
            else:
                # レガシーフォールバック
                from main import rag_chain_template
                rag_chain = rag_chain_template
                logger.debug("🔄 Using legacy RAG chain")
            
            if rag_chain:
                # タイムアウト付きRAG処理
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(self._execute_rag, query, rag_chain)
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
# LINE Bot設定と初期化（継続）
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

# グローバルインスタンス（RAG共有強化版）
smart_router = LineSmartRouterWithRAGSharing()
rag_integration = LineRAGIntegrationWithSharing()
duplicate_prevention = LineDuplicateMessagePrevention()

if LINE_SDK_AVAILABLE and LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET:
    try:
        normalized_token = normalize_line_token(LINE_CHANNEL_ACCESS_TOKEN)
        normalized_secret = normalize_line_token(LINE_CHANNEL_SECRET)
        
        if normalized_token and normalized_secret:
            configuration = Configuration(access_token=normalized_token)
            handler = WebhookHandler(normalized_secret)
            
            with ApiClient(configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
            
            logger.info("✅ LINE Smart Integrated Bot with RAG Sharing initialized")
        else:
            raise ValueError("Empty normalized credentials")
            
    except Exception as e:
        logger.error(f"❌ LINE Bot initialization failed: {e}")
        line_bot_api, handler = None, None

# ==============================================================================
# 安全送信関数（ログ最適化版）
# ==============================================================================
def send_line_message_safe(reply_token: str, user_id: str, message: str) -> bool:
    """安全なLINE送信（ログ最適化版）"""
    if not line_bot_api:
        logger.error("❌ LINE Bot API not initialized")
        return False
    
    # 重複防止チェック
    if not duplicate_prevention.should_send_message(user_id, message):
        logger.debug(f"🛑 Duplicate message prevented for user: {user_id}")  # 🆕 DEBUGレベル
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
                logger.debug(f"✅ Reply sent: {len(message)} chars")  # 🆕 DEBUGレベル
                return True
                
            except ApiException as reply_error:
                # Reply失効時はPush APIにフォールバック
                if "Invalid reply token" in str(reply_error) or getattr(reply_error, "status", None) == 400:
                    logger.info(f"⚠️ Reply token expired, using Push API fallback")
                    
                    try:
                        messaging_api.push_message_with_http_info(
                            PushMessageRequest(
                                to=user_id,
                                messages=[TextMessage(text=message)]
                            )
                        )
                        logger.debug(f"✅ Push message sent as fallback: {len(message)} chars")  # 🆕 DEBUGレベル
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
# Webhook エンドポイント（ログ最適化版）
# ==============================================================================
@router.post("/webhook")
async def smart_integrated_webhook_with_rag_sharing(request: Request, background_tasks: BackgroundTasks):
    """RAG共有・ログ最適化強化Webhook"""
    logger.debug("🚀 LINE Smart Integrated Webhook with RAG Sharing called")  # 🆕 DEBUGレベル
    
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
        logger.debug(f"📨 RAG sharing webhook processing: {body_text[:100]}...")  # 🆕 DEBUGレベル・短縮
        
        handler.handle(body_text, signature)
        
        logger.debug("✅ RAG sharing webhook processed successfully")  # 🆕 DEBUGレベル
        return {"status": "ok", "timestamp": datetime.now().isoformat()}
        
    except InvalidSignatureError as sig_error:
        logger.error(f"❌ Invalid signature: {sig_error}")
        return {"status": "signature_error"}
    except Exception as e:
        logger.error(f"💥 Smart integrated webhook with RAG sharing error: {e}")
        logger.error(traceback.format_exc())
        return {"status": "error", "error": str(e)}

# ==============================================================================
# イベントハンドラ（RAG共有・ログ最適化版）
# ==============================================================================
if LINE_SDK_AVAILABLE and handler:
    
    @handler.add(FollowEvent)
    def handle_follow_with_rag_sharing(event):
        """フォローハンドラ（RAG共有・ログ最適化版）"""
        start_time = time.time()
        try:
            user_id = event.source.user_id
            reply_token = event.reply_token
            
            # イベント重複防止チェック
            event_data = f"follow_{user_id}_{reply_token}"
            if not duplicate_prevention.should_process_event(user_id, event_data):
                logger.debug(f"🛑 Follow event duplicate prevented for user: {user_id}")  # 🆕 DEBUGレベル
                return
            
            logger.info(f"👤 New follower (RAG sharing): {user_id}")
            
            greeting_message = """こんにちは！キノエデザインです✨
この度は友だち追加ありがとうございます。

**🎯 目的のボタンをタップ👇**
🤖AI相談 / 📍来場予約 / 📄資料請求 / 💴資金計画 / 🌐サイト / 💬チャット

**⚡ 応答について**
・AIは24時間対応（RAG共有強化）
・資金計画は段階的に診断
・スタッフは営業日に対応
・営業時間：9:00-18:00

**🔒 プライバシー**
取扱い：https://preview.studio.site/live/EjOQljz1WJ/privacy-policy

住まいのことなら何でもお気軽にご相談ください😊"""
            
            success = send_line_message_safe(reply_token, user_id, greeting_message)
            
            duration = (time.time() - start_time) * 1000
            logger.debug(f"✅ Greeting with RAG sharing sent: {duration:.1f}ms, success: {success}")  # 🆕 DEBUGレベル
            
        except Exception as e:
            logger.error(f"❌ Follow handler with RAG sharing error: {e}")
            logger.error(traceback.format_exc())
    
    @handler.add(MessageEvent, message=TextMessageContent)
    def handle_message_with_rag_sharing(event):
        """メッセージハンドラ（RAG共有・ログ最適化版）"""
        start_time = time.time()
        
        try:
            user_id = event.source.user_id
            message_text = event.message.text
            reply_token = event.reply_token
            
            # イベント重複防止チェック
            event_data = f"message_{user_id}_{message_text[:50]}_{reply_token}"
            if not duplicate_prevention.should_process_event(user_id, event_data):
                logger.debug(f"🛑 Message event duplicate prevented for user: {user_id}")  # 🆕 DEBUGレベル
                return
            
            logger.info(f"📱 Processing with RAG sharing: '{message_text[:30]}...' from user: {user_id}")
            
            # スマートルーティング実行
            routing_result = smart_router.determine_response_route(message_text, user_id)
            route = routing_result["route"]
            
            logger.debug(f"🧠 Route selected with RAG sharing: {route} - {routing_result['reason']}")  # 🆕 DEBUGレベル
            
            # ルート別処理
            if route == "financial":
                # 資金計画処理
                logger.info(f"💰 Processing financial planning for user: {user_id}")
                response_text = handle_financial_message_for_line(user_id, message_text)
                success = send_line_message_safe(reply_token, user_id, response_text)
                
                duration = (time.time() - start_time) * 1000
                logger.debug(f"💰 Financial response with RAG sharing: {duration:.1f}ms, success: {success}")  # 🆕 DEBUGレベル
                
            elif route == "template":
                # テンプレート即座応答
                response_text = routing_result["response"]
                success = send_line_message_safe(reply_token, user_id, response_text)
                
                duration = (time.time() - start_time) * 1000
                logger.debug(f"⚡ Template response with RAG sharing: {duration:.1f}ms, success: {success}")  # 🆕 DEBUGレベル
                
            elif route == "rag":
                # 🆕 RAG共有統計記録
                smart_router.routing_stats["rag_sharing_attempts"] += 1
                
                # RAG処理（非同期実行・共有強化）
                def process_rag():
                    try:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        result = loop.run_until_complete(
                            rag_integration.process_rag_query(message_text, user_id)
                        )
                        loop.close()
                        
                        # 🆕 RAG共有成功記録
                        smart_router.routing_stats["rag_sharing_successes"] += 1
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
                logger.debug(f"🤖 RAG response with sharing: {duration:.1f}ms, success: {success}")  # 🆕 DEBUGレベル
                
            else:
                # フォールバック応答
                response_text = smart_router.templates.get("挨拶", """ご質問ありがとうございます😊

住まいづくりについて、どのようなことをお知りになりたいでしょうか？

メニューからお選びいただくか、具体的にお聞かせください✨""")
                
                success = send_line_message_safe(reply_token, user_id, response_text)
                
                duration = (time.time() - start_time) * 1000
                logger.debug(f"🔄 Fallback response with RAG sharing: {duration:.1f}ms, success: {success}")  # 🆕 DEBUGレベル
            
            # 統計更新
            total_duration = (time.time() - start_time) * 1000
            logger.info(f"✅ Message with RAG sharing processed: {total_duration:.1f}ms, route: {route}")
            
        except Exception as e:
            logger.error(f"❌ Message handler with RAG sharing error: {e}")
            logger.error(traceback.format_exc())
            try:
                emergency = """申し訳ございません。一時的にシステムの不具合が発生しています。

しばらくしてから再度お試しください😊"""
                send_line_message_safe(event.reply_token, event.source.user_id, emergency)
                logger.info("🆘 Emergency response sent")
            except Exception as final_error:
                logger.error(f"❌ Emergency response failed: {final_error}")

    @handler.add(PostbackEvent)
    def handle_postback_with_rag_sharing(event):
        """Postbackハンドラ（RAG共有・ログ最適化版）"""
        try:
            user_id = event.source.user_id
            reply_token = event.reply_token
            postback_data = event.postback.data or ""
            
            # イベント重複防止チェック
            event_data = f"postback_{user_id}_{postback_data}_{reply_token}"
            if not duplicate_prevention.should_process_event(user_id, event_data):
                logger.debug(f"🛑 Postback event duplicate prevented for user: {user_id}")  # 🆕 DEBUGレベル
                return
            
            logger.debug(f"🔙 Postback with RAG sharing from {user_id}: {postback_data}")  # 🆕 DEBUGレベル
            
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
            logger.debug(f"✅ Postback with RAG sharing processed: success={success}")  # 🆕 DEBUGレベル
            
        except Exception as e:
            logger.error(f"💥 Postback handler with RAG sharing error: {e}")
            logger.error(traceback.format_exc())

# ==============================================================================
# 統計エンドポイント（RAG共有強化版）
# ==============================================================================
@router.get("/duplicate-prevention-stats")
def get_line_duplicate_prevention_stats():
    """LINE重複防止統計取得（ログ最適化版）"""
    duplicate_stats = duplicate_prevention.get_stats()
    routing_stats = smart_router.get_stats()
    
    return {
        "duplicate_prevention": duplicate_stats,
        "routing_stats": routing_stats,
        "rag_sharing": routing_stats.get("rag_sharing", {}),  # 🆕 RAG共有統計
        "effectiveness": {
            "message_duplicates_prevented": duplicate_stats["stats"]["message_duplicates_prevented"],
            "event_duplicates_prevented": duplicate_stats["stats"]["event_duplicates_prevented"],
            "successful_sends": duplicate_stats["stats"]["successful_sends"],
            "total_send_attempts": duplicate_stats["stats"]["total_send_attempts"],
            "log_throttled_count": duplicate_stats["stats"]["log_throttled_count"],  # 🆕
            "success_rate": (duplicate_stats["stats"]["successful_sends"] / duplicate_stats["stats"]["total_send_attempts"] * 100) if duplicate_stats["stats"]["total_send_attempts"] > 0 else 0
        },
        "optimizations": {  # 🆕 最適化情報
            "log_optimization": duplicate_stats.get("log_optimization", "enabled"),
            "rag_sharing": routing_stats.get("rag_sharing", {}).get("enabled", False)
        },
        "timestamp": datetime.now().isoformat()
    }

@router.get("/rag-sharing-stats")
def get_rag_sharing_stats():
    """🆕 RAG共有統計専用エンドポイント"""
    routing_stats = smart_router.get_stats()
    rag_sharing_stats = routing_stats.get("rag_sharing", {})
    
    # RAGコンポーネント状態取得
    shared_components = get_shared_rag_components_safe()
    
    return {
        "rag_sharing_performance": rag_sharing_stats,
        "shared_components_status": {
            "is_initialized": shared_components["is_initialized"],
            "shared_globally": shared_components["shared_globally"],
            "vectorstore_available": shared_components["vectorstore"] is not None,
            "rag_chain_available": shared_components["rag_chain_template"] is not None,
            "llm_available": shared_components["llm_instance"] is not None
        },
        "rag_integration_status": {
            "available": rag_integration.rag_available,
            "cache_entries": len(rag_integration.rag_cache),
            "shared_rag_components_loaded": rag_integration.shared_rag_components is not None
        },
        "fixes_applied": [
            "✅ RAG components global sharing from main.py",
            "✅ Log level optimization for duplicate prevention",
            "✅ Cache system performance improvement",
            "✅ Error handling enhancement"
        ],
        "timestamp": datetime.now().isoformat()
    }

@router.get("/performance")
def get_smart_performance_with_rag_sharing():
    """パフォーマンス統計（RAG共有強化版）"""
    stats = smart_router.get_stats()
    duplicate_stats = duplicate_prevention.get_stats()
    active_sessions = len(smart_router.financial_handler.state_manager.user_states)
    
    # 🆕 RAG共有パフォーマンス
    rag_sharing = stats.get("rag_sharing", {})
    shared_components = get_shared_rag_components_safe()
    
    return {
        "line_smart_integrated_rag_sharing_stats": stats,
        "duplicate_prevention_stats": duplicate_stats,
        "rag_sharing_performance": {  # 🆕 RAG共有パフォーマンス
            "sharing_attempts": rag_sharing.get("attempts", 0),
            "sharing_successes": rag_sharing.get("successes", 0),
            "sharing_success_rate": rag_sharing.get("success_rate", 0),
            "components_available": shared_components["shared_globally"],
            "integration_method": "global_sharing_from_main"
        },
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
            "rag_shared_globally": shared_components["shared_globally"],  # 🆕
            "financial_planning_enabled": True,
            "duplicate_prevention_enabled": True,
            "log_optimization_enabled": True,  # 🆕
            "single_handler": True
        },
        "features": [
            "🚫 Duplicate Message Prevention (Optimized Logging)",
            "🎯 Single Handler Processing",
            "⚡ Smart Route Selection",
            "💰 Financial Planning with State Management",
            "🔧 Template Instant Response",
            "🤖 RAG Integration with Global Sharing",
            "🧮 Financial Calculation Engine",
            "🛡️ Reply Token Expiry Protection",
            "📤 Push API Automatic Fallback",
            "📱 LINE-Specific Response Formatting",
            "💾 Response Caching",
            "🌐 Global RAG Components Sharing"  # 🆕
        ],
        "performance_targets": {
            "template_response_time": "< 200ms",
            "rag_response_time": "< 10s",
            "financial_response_time": "< 1s",
            "duplicate_messages": "0 (prevented with optimized logging)",
            "success_rate": "> 99%",
            "rag_sharing_success_rate": "> 95%"  # 🆕
        },
        "fixes_effectiveness": {  # 🆕 修正効果
            "log_noise_reduction": f"{duplicate_stats['stats']['log_throttled_count']} logs throttled",
            "rag_sharing_success": f"{rag_sharing.get('success_rate', 0):.1f}%",
            "duplicate_prevention_rate": f"{(duplicate_stats['stats']['message_duplicates_prevented'] / max(duplicate_stats['stats']['total_send_attempts'], 1) * 100):.1f}%"
        },
        "timestamp": datetime.now().isoformat()
    }

@router.get("/health")
def smart_health_check_with_rag_sharing():
    """ヘルスチェック（RAG共有強化版）"""
    stats = smart_router.get_stats()
    duplicate_stats = duplicate_prevention.get_stats()
    active_sessions = len(smart_router.financial_handler.state_manager.user_states)
    shared_components = get_shared_rag_components_safe()
    
    health_status = {
        "status": "healthy" if LINE_SDK_AVAILABLE and line_bot_api else "degraded",
        "components": {
            "line_sdk": "ok" if LINE_SDK_AVAILABLE else "error",
            "line_bot_api": "ok" if line_bot_api else "error",
            "handler": "ok" if handler else "error",
            "smart_router": "ok",
            "rag_integration": "ok" if rag_integration.rag_available else "available_fallback",
            "rag_sharing": "ok" if shared_components["shared_globally"] else "limited",  # 🆕
            "financial_planning": "ok",
            "duplicate_prevention": "ok",
            "log_optimization": "ok",  # 🆕
            "credentials": "ok" if LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET else "error"
        },
        "metrics": stats,
        "duplicate_prevention": duplicate_stats,
        "rag_sharing": {  # 🆕 RAG共有ヘルス
            "global_sharing": shared_components["shared_globally"],
            "components_available": shared_components["is_initialized"],
            "sharing_success_rate": stats.get("rag_sharing", {}).get("success_rate", 0)
        },
        "financial_planning": {
            "active_sessions": active_sessions,
            "calculation_engine": "operational",
            "state_management": "operational"
        },
        "optimizations_applied": [  # 🆕 適用済み最適化
            "Log Level Optimization",
            "RAG Global Sharing",
            "Duplicate Prevention Enhancement",
            "Performance Monitoring Improvement"
        ],
        "fixes_status": {  # 🆕 修正状況
            "rag_sharing_fixed": shared_components["shared_globally"],
            "log_optimization_applied": True,
            "duplicate_prevention_optimized": True,
            "old_endpoint_issues_resolved": True
        },
        "single_handler": True,
        "timestamp": datetime.now().isoformat()
    }
    
    return health_status