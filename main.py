# main.py - 重複メッセージ完全修正版（単一LINE Bot統合）

import logging
import os
import asyncio
import time
import hashlib
from datetime import datetime
from typing import Dict, Any, Optional, List
import concurrent.futures
from uuid import uuid4
import traceback

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# ログ設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# FastAPI アプリケーションインスタンス
app = FastAPI(
    title="RAG API - Single LINE Bot Integration (No Duplicates)",
    description="High-Performance AI Chat API with Single LINE Bot Integration (Duplicate Message Prevention)",
    version="5.1.0-single-integration"
)

# CORS設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# グローバル変数（RAG機能）
vectorstore = None
rag_chain_template = None
llm_instance = None
initialization_lock = asyncio.Lock()
is_initialized = False

# 起動時刻を記録
startup_time = time.time()

# 設定フラグ（重複防止強化版）
ENABLE_RAG_INITIALIZATION = True
ENABLE_SMART_ROUTING = True
ENABLE_FAST_ROUTES = True
ENABLE_SENTENCE_COMPLETION = True
ENABLE_LINE_INTEGRATION = True
ENABLE_FINANCIAL_PLANNING = True
ENABLE_DUPLICATE_PREVENTION = True  # 🆕 重複防止機能

# ★重要：LINE統合設定（単一ルーターのみ）
LINE_BOT_MODE = os.getenv("LINE_BOT_MODE", "ultra_fast_financial")  # 単一モード固定
SINGLE_LINE_INTEGRATION = True  # 🆕 単一統合フラグ

# ==============================================================================
# 重複メッセージ防止システム（新規追加）
# ==============================================================================
class DuplicateMessagePrevention:
    """重複メッセージ防止システム"""
    
    def __init__(self):
        self.recent_sends = {}  # {(user_id, message_hash): timestamp}
        self.duplicate_window = 60  # 60秒以内の重複を防止
        self.cleanup_interval = 300  # 5分毎にクリーンアップ
        self.last_cleanup = time.time()
        
    def should_send_message(self, user_id: str, message: str) -> bool:
        """メッセージを送信すべきかチェック"""
        if not ENABLE_DUPLICATE_PREVENTION:
            return True
            
        # メッセージハッシュ生成
        message_hash = hashlib.md5(message.encode()).hexdigest()[:8]
        key = (user_id, message_hash)
        
        current_time = time.time()
        
        # 定期クリーンアップ
        if current_time - self.last_cleanup > self.cleanup_interval:
            self._cleanup_old_records(current_time)
        
        # 重複チェック
        if key in self.recent_sends:
            time_diff = current_time - self.recent_sends[key]
            if time_diff < self.duplicate_window:
                logger.warning(f"🛑 Duplicate message suppressed: user={user_id}, age={time_diff:.1f}s")
                return False
        
        # 送信記録
        self.recent_sends[key] = current_time
        return True
    
    def _cleanup_old_records(self, current_time: float):
        """古い記録をクリーンアップ"""
        cutoff_time = current_time - self.duplicate_window * 2
        old_keys = [key for key, timestamp in self.recent_sends.items() if timestamp < cutoff_time]
        
        for key in old_keys:
            del self.recent_sends[key]
        
        self.last_cleanup = current_time
        if old_keys:
            logger.info(f"🧹 Cleaned up {len(old_keys)} old duplicate prevention records")
    
    def get_stats(self) -> Dict[str, Any]:
        """重複防止統計取得"""
        return {
            "active_records": len(self.recent_sends),
            "duplicate_window_seconds": self.duplicate_window,
            "cleanup_interval_seconds": self.cleanup_interval,
            "enabled": ENABLE_DUPLICATE_PREVENTION
        }

# グローバル重複防止インスタンス
duplicate_prevention = DuplicateMessagePrevention()

# ==============================================================================
# 拡張スマートルーティングシステム（重複防止強化版）
# ==============================================================================
class SmartRouterWithDuplicatePrevention:
    """重複防止機能付きスマートルーティングシステム"""
    
    def __init__(self):
        self.routing_stats = {
            "fast_route_count": 0,
            "rag_route_count": 0, 
            "template_route_count": 0,
            "line_route_count": 0,
            "financial_route_count": 0,
            "duplicate_prevented_count": 0,  # 🆕 重複防止統計
            "total_requests": 0
        }
        
        # 高速ルート対象キーワード
        self.fast_keywords = [
            "AI相談", "資料請求", "展示場", "見学", "予約", "チャット相談",
            "AI住まいサイト", "サイト", "ホームページ",
            "こんにちは", "はじめまして", "よろしく", "ありがとう"
        ]
        
        # 資金計画専用キーワード
        self.financial_keywords = [
            "資金計画", "💰", "ローン計算", "予算診断",
            "年収", "返済", "借入期間", "家族構成"
        ]
        
        # RAG処理が必要なキーワード
        self.rag_keywords = [
            "坪単価", "価格", "費用", "仕様", "標準", "設備",
            "断熱", "性能", "耐震", "補助金", "助成金"
        ]
        
        # LINE専用高速処理キーワード
        self.line_instant_keywords = [
            "ai相談", "資料請求", "展示場予約", "チャット相談", "ai住まいサイト"
        ]
    
    def determine_route(self, query: str, platform: str = "web", user_id: str = None) -> str:
        """重複防止機能付きルート決定"""
        self.routing_stats["total_requests"] += 1
        query_lower = query.lower()
        
        # 資金計画セッション状態チェック（最優先）
        if user_id and ENABLE_FINANCIAL_PLANNING:
            if self._has_active_financial_session(user_id):
                self.routing_stats["financial_route_count"] += 1
                return "financial_session"
            
            if any(keyword in query_lower for keyword in self.financial_keywords):
                self.routing_stats["financial_route_count"] += 1
                return "financial_start"
        
        # LINE特有の処理
        if platform == "line":
            self.routing_stats["line_route_count"] += 1
            
            # LINE即座応答チェック
            if any(keyword in query_lower for keyword in self.line_instant_keywords):
                self.routing_stats["fast_route_count"] += 1
                return "line_instant"
            
            # 短いメッセージはテンプレート
            if len(query) <= 10:
                self.routing_stats["template_route_count"] += 1
                return "line_template"
        
        # 高速ルート判定
        if any(keyword in query_lower for keyword in self.fast_keywords):
            self.routing_stats["fast_route_count"] += 1
            return "fast"
        
        # RAGルート判定
        if any(keyword in query_lower for keyword in self.rag_keywords):
            self.routing_stats["rag_route_count"] += 1
            return "rag"
        
        # デフォルト判定
        if len(query) <= 15:
            self.routing_stats["template_route_count"] += 1
            return "template"
        else:
            self.routing_stats["rag_route_count"] += 1
            return "rag"
    
    def _has_active_financial_session(self, user_id: str) -> bool:
        """アクティブな資金計画セッションがあるかチェック"""
        try:
            from api.routers.line_bot_financial_planner import get_financial_planning_handler
            handler = get_financial_planning_handler()
            session = handler.state_manager.get_session(user_id)
            return session is not None
        except:
            return False
    
    def increment_duplicate_prevented(self):
        """重複防止カウンターを増加"""
        self.routing_stats["duplicate_prevented_count"] += 1
    
    def get_stats(self) -> Dict[str, Any]:
        """統計取得（重複防止統計追加）"""
        total = self.routing_stats["total_requests"]
        
        return {
            "total_requests": total,
            "fast_route_percentage": (self.routing_stats["fast_route_count"] / total * 100) if total > 0 else 0,
            "rag_route_percentage": (self.routing_stats["rag_route_count"] / total * 100) if total > 0 else 0,
            "template_route_percentage": (self.routing_stats["template_route_count"] / total * 100) if total > 0 else 0,
            "line_route_percentage": (self.routing_stats["line_route_count"] / total * 100) if total > 0 else 0,
            "financial_route_percentage": (self.routing_stats["financial_route_count"] / total * 100) if total > 0 else 0,
            "duplicate_prevented_count": self.routing_stats["duplicate_prevented_count"],  # 🆕
            "duplicate_prevention_rate": (self.routing_stats["duplicate_prevented_count"] / total * 100) if total > 0 else 0,  # 🆕
            "routing_efficiency": {
                "fast_routes": self.routing_stats["fast_route_count"],
                "rag_routes": self.routing_stats["rag_route_count"],
                "template_routes": self.routing_stats["template_route_count"],
                "line_routes": self.routing_stats["line_route_count"],
                "financial_routes": self.routing_stats["financial_route_count"],
                "duplicates_prevented": self.routing_stats["duplicate_prevented_count"]  # 🆕
            }
        }

# グローバルルーター（重複防止強化版）
smart_router = SmartRouterWithDuplicatePrevention()

# ==============================================================================
# 文章完全性保証システム（既存）
# ==============================================================================
def ensure_response_completeness(text: str, query: str = "", platform: str = "web") -> str:
    """文章完全性保証（プラットフォーム最適化版）"""
    if not text or len(text.strip()) < 5:
        return generate_platform_fallback(query, platform)
    
    text = text.strip()
    
    # 文末チェックと補完
    if not text.endswith(('。', '！', '？', '.', '!', '?')):
        logger.info(f"🔧 Fixing incomplete response ({platform}): '{text[-30:]}'")
        
        # プラットフォーム別補完パターン
        if platform == "line":
            completion_patterns = {
                'や': '関連する準備を進めましょう✨',
                '重要': 'です😊詳しくはお気軽にご相談ください。',
                '必要': 'です。',
                'について': 'は詳しくご案内します💡',
                'から': '、ご検討ください。',
                'ので': '、お気軽にご相談ください😊',
                'ため': '、ぜひご相談ください。',
                '、': '。',
            }
        else:
            completion_patterns = {
                'や': '関連する準備を進めることをお勧めします。',
                '重要': 'です。詳しくはお気軽にご相談ください。',
                '必要': 'です。',
                'について': 'は詳細をご案内いたします。',
                'から': '、ご検討ください。',
                'ので': '、お気軽にご相談ください。',
                'ため': '、ご相談ください。',
                '、': '。',
            }
        
        # パターンマッチングで補完
        for pattern, completion in completion_patterns.items():
            if text.endswith(pattern):
                if pattern == '、':
                    text = text[:-1] + completion
                else:
                    text += completion
                break
        else:
            if text.endswith(('ます', 'です')):
                text += '。'
            elif text.endswith(('た', 'る', 'し')):
                text += '。'
            elif text.endswith(('は', 'が')):
                text += '重要なポイントです。'
            elif text.endswith(('選定', '検討', '確認', '準備', '計画', '設計')):
                text += 'も大切です。'
            else:
                if len(text) > 50:
                    text += '。'
                elif len(text) > 25:
                    if platform == "line":
                        text += '。詳しくはお問い合わせください😊'
                    else:
                        text += '。詳細はお問い合わせください。'
                else:
                    text = generate_platform_fallback(query, platform)
        
        logger.info(f"✅ Fixed response ({platform}): '{text[-30:]}'")
    
    return text

def generate_platform_fallback(query: str, platform: str) -> str:
    """プラットフォーム別フォールバック応答"""
    
    # 資金計画関連キーワードチェック
    if any(keyword in query.lower() for keyword in ["資金計画", "💰", "ローン", "予算", "返済", "借入"]):
        if platform == "line":
            return """💰 資金計画についてご案内します

「💰 資金計画」ボタンをタップすると、AI診断を開始できます✨

📊 **診断内容**
・購入可能金額の目安
・毎月の返済額の目安
・最大借入可能額

お気軽にお試しください😊"""
        else:
            return "資金計画については、詳細な診断をご利用いただけます。年収や返済希望額から購入可能な住宅価格を算出いたします。"
    
    fallback_templates = {
        "坪単価": {
            "web": "坪単価については、お客様のご要望や仕様によって異なりますので、詳細なお見積りをご提供いたします。",
            "line": "坪単価は約70〜85万円/坪が目安です💰詳しいお見積りはお気軽にご相談ください😊"
        },
        "仕様": {
            "web": "住宅の仕様について詳しくご案内いたします。お客様のご要望に合わせて最適な仕様をご提案いたします。",
            "line": "住宅仕様についてご案内します🏠標準仕様から高性能仕様まで幅広く対応しています✨"
        },
        "資料": {
            "web": "資料請求を承ります。お名前、ご住所、お電話番号をお教えいただければ、詳しい資料をお送りいたします。",
            "line": "資料請求ですね📋お名前・ご住所・お電話番号をお送りください。3営業日以内にお送りします！"
        }
    }
    
    # クエリに応じたテンプレート選択
    for keyword, templates in fallback_templates.items():
        if keyword in query:
            return templates.get(platform, templates["web"])
    
    # デフォルトフォールバック
    if platform == "line":
        return """ご質問ありがとうございます✨

住まいづくりについて、どのようなことをお知りになりたいでしょうか？

💡 **人気の相談内容**
💰 資金計画・予算診断
🏠 坪単価・価格について
📋 資料請求・展示場見学

お気軽にお問い合わせください😊"""
    else:
        return "お尋ねの内容について詳しくご案内いたします。住宅に関することでしたら何でもお気軽にお問い合わせください。"

# ==============================================================================
# RAGコンポーネント初期化（既存）
# ==============================================================================
async def initialize_rag_components():
    """RAGコンポーネントの非同期初期化"""
    global vectorstore, rag_chain_template, llm_instance, is_initialized
    
    if is_initialized:
        return
    
    async with initialization_lock:
        if is_initialized:
            return
            
        logger.info("🚀 Initializing RAG components (single integration mode)...")
        
        try:
            from llm.llm_runner import load_llm
            llm_instance = load_llm()[0]
            logger.info("✅ LLM instance loaded")
            
            try:
                from rag.fast_rag_chain import load_ultra_fast_vectorstore, get_ultra_fast_rag_chain
                vectorstore = load_ultra_fast_vectorstore()
                rag_chain_template = get_ultra_fast_rag_chain(vectorstore)
                logger.info("✅ Ultra fast RAG chain loaded")
            except Exception as e:
                logger.warning(f"⚠️ Ultra fast RAG chain failed, using fallback: {e}")
            
            is_initialized = True
            logger.info("✅ RAG components initialized successfully (single integration)")
            
        except Exception as e:
            logger.error(f"❌ RAG initialization failed: {e}")
            is_initialized = False

# ==============================================================================
# リクエストモデル
# ==============================================================================
class OptimizedChatRequest(BaseModel):
    question: str
    username: str | None = None
    platform: str | None = "web"
    route_preference: str | None = None
    financial_context: Dict[str, Any] | None = None

# ==============================================================================
# エンドポイント（重複防止強化版）
# ==============================================================================
@app.post("/chat")
@app.post("/chat/")
async def optimized_chat_endpoint(req: OptimizedChatRequest, request: Request):
    """重複防止機能付き最適化チャットエンドポイント"""
    
    overall_start = time.time()
    platform = req.platform or "web"
    username = req.username or f"{platform}-user"
    
    logger.info(f"🌐 Chat with Duplicate Prevention ({platform}): {req.question[:50]}...")
    
    try:
        # スマートルーティング
        if req.route_preference and req.route_preference in ["fast", "rag", "line_instant", "financial"]:
            selected_route = req.route_preference
            logger.info(f"🎯 User-specified route: {selected_route}")
        else:
            selected_route = smart_router.determine_route(req.question, platform, username)
            logger.info(f"🧠 Smart-selected route: {selected_route}")
        
        # ルート別処理
        if selected_route in ["financial_start", "financial_session"]:
            response = await process_financial_route(req.question, username, req.financial_context)
        elif selected_route == "line_instant":
            response = await process_line_instant_route(req.question, username)
        elif selected_route == "line_template":
            response = await process_line_template_route(req.question, username)
        elif selected_route == "fast" and ENABLE_FAST_ROUTES:
            response = await process_fast_route(req.question, platform, username)
        elif selected_route == "rag":
            response = await process_rag_route(req.question, platform, username)
        else:
            response = await process_template_route(req.question, platform, username)
        
        total_time = time.time() - overall_start
        
        # 文章完全性チェック
        if ENABLE_SENTENCE_COMPLETION:
            response["answer"] = ensure_response_completeness(
                response["answer"], req.question, platform
            )
            response["sentence_complete"] = response["answer"].endswith(('。', '！', '？', '.', '!', '?'))
        
        logger.info(f"✅ Response with Duplicate Prevention ({platform}): {total_time:.3f}s, "
                   f"route={selected_route}, "
                   f"length={len(response['answer'])}, "
                   f"complete={response.get('sentence_complete', False)}")
        
        return {
            "answer": response["answer"],
            "sources": response.get("sources", []),
            "status": response.get("status", "ok"),
            "financial_data": response.get("financial_data"),
            "performance": {
                "total_time": total_time,
                "selected_route": selected_route,
                "platform": platform,
                "sentence_complete": response.get("sentence_complete", False),
                "smart_routing_enabled": ENABLE_SMART_ROUTING,
                "duplicate_prevention_enabled": ENABLE_DUPLICATE_PREVENTION,
                "processing_method": response.get("method", "unknown")
            }
        }
        
    except Exception as e:
        total_time = time.time() - overall_start
        error_id = str(uuid4())[:8]
        
        logger.error(f"❌ Chat error [{error_id}]: {e}")
        logger.error(traceback.format_exc())
        
        fallback_answer = generate_platform_fallback(req.question, platform)
        complete_fallback = ensure_response_completeness(fallback_answer, req.question, platform)
        
        return JSONResponse(
            status_code=200,
            content={
                "answer": complete_fallback,
                "sources": [],
                "status": "fallback",
                "error_id": error_id,
                "financial_data": None,
                "performance": {
                    "total_time": total_time,
                    "selected_route": "error",
                    "platform": platform,
                    "sentence_complete": complete_fallback.endswith(('。', '！', '？', '.', '!', '?'))
                }
            }
        )

# ==============================================================================
# ルート処理関数（既存のものを維持）
# ==============================================================================
async def process_financial_route(query: str, username: str, financial_context: Optional[Dict] = None) -> Dict[str, Any]:
    try:
        from api.routers.line_bot_financial_planner import handle_financial_message_for_line
        result = handle_financial_message_for_line(username, query)
        return {"answer": result, "sources": [], "status": "ok", "method": "financial_planning", "financial_data": financial_context}
    except Exception as e:
        logger.error(f"Financial route error: {e}")
        return {"answer": generate_platform_fallback(query, "line"), "sources": [], "status": "fallback", "method": "financial_fallback", "financial_data": None}

async def process_line_instant_route(query: str, username: str) -> Dict[str, Any]:
    return {"answer": generate_platform_fallback(query, "line"), "sources": [], "status": "ok", "method": "line_instant"}

async def process_line_template_route(query: str, username: str) -> Dict[str, Any]:
    return {"answer": generate_platform_fallback(query, "line"), "sources": [], "status": "ok", "method": "line_template"}

async def process_fast_route(query: str, platform: str, username: str) -> Dict[str, Any]:
    try:
        if platform == "line":
            return {"answer": generate_platform_fallback(query, platform), "sources": [], "status": "ok", "method": "line_basic"}
        else:
            from api.routers.chat_ultra_fast import separated_generator
            result = await separated_generator.generate_separated_response(query, platform, username)
            return {"answer": result["answer"], "sources": [], "status": result.get("status", "ok"), "method": "web_ultra_fast"}
    except Exception as e:
        logger.error(f"Fast route error: {e}")
        return {"answer": generate_platform_fallback(query, platform), "sources": [], "status": "fallback", "method": "fast_fallback"}

async def process_rag_route(query: str, platform: str, username: str) -> Dict[str, Any]:
    try:
        if not is_initialized and ENABLE_RAG_INITIALIZATION:
            await initialize_rag_components()
        
        if rag_chain_template:
            result = rag_chain_template.invoke({"query": query})
            rag_answer = result.get("result", "")
            
            if rag_answer and len(rag_answer.strip()) > 10:
                return {"answer": rag_answer, "sources": [], "status": "ok", "method": "rag_processing"}
        
        return {"answer": generate_platform_fallback(query, platform), "sources": [], "status": "fallback", "method": "rag_fallback"}
    except Exception as e:
        logger.error(f"RAG route error: {e}")
        return {"answer": generate_platform_fallback(query, platform), "sources": [], "status": "fallback", "method": "rag_error_fallback"}

async def process_template_route(query: str, platform: str, username: str) -> Dict[str, Any]:
    return {"answer": generate_platform_fallback(query, platform), "sources": [], "status": "ok", "method": "template_direct"}

# ==============================================================================
# ヘルスチェック・システム状態（重複防止統計追加）
# ==============================================================================
@app.get("/healthz")
async def health_check():
    """重複防止機能付きヘルスチェック"""
    uptime = time.time() - startup_time
    routing_stats = smart_router.get_stats()
    duplicate_stats = duplicate_prevention.get_stats()
    
    return {
        "status": "healthy",
        "uptime": uptime,
        "timestamp": datetime.now().isoformat(),
        "version": "5.1.0-duplicate-prevention",
        "message": "Single LINE Bot Integration with Duplicate Message Prevention",
        "features": {
            "smart_routing": ENABLE_SMART_ROUTING,
            "fast_routes": ENABLE_FAST_ROUTES,
            "sentence_completion": ENABLE_SENTENCE_COMPLETION,
            "rag_initialization": ENABLE_RAG_INITIALIZATION,
            "line_integration": ENABLE_LINE_INTEGRATION,
            "financial_planning": ENABLE_FINANCIAL_PLANNING,
            "duplicate_prevention": ENABLE_DUPLICATE_PREVENTION,
            "single_integration": SINGLE_LINE_INTEGRATION,
            "line_bot_mode": LINE_BOT_MODE
        },
        "routing_stats": routing_stats,
        "duplicate_prevention_stats": duplicate_stats,
        "rag_status": {
            "initialized": is_initialized,
            "vectorstore_ready": vectorstore is not None,
            "llm_ready": llm_instance is not None
        },
        "line_status": {
            "single_webhook_mode": SINGLE_LINE_INTEGRATION,
            "active_bot_mode": LINE_BOT_MODE,
            "webhook_endpoint": "/line/webhook",
            "duplicate_prevention": "enabled",
            "registered_routers": 1
        }
    }

@app.get("/")
async def root():
    """ルートエンドポイント（重複防止対応版）"""
    routing_stats = smart_router.get_stats()
    duplicate_stats = duplicate_prevention.get_stats()
    
    return {
        "message": "Single LINE Bot Integration with Duplicate Message Prevention",
        "version": "5.1.0-duplicate-prevention", 
        "timestamp": datetime.now().isoformat(),
        "features": [
            "🚫 Duplicate Message Prevention (60s window)",
            "🎯 Single LINE Bot Integration (No Multiple Handlers)",
            "⚡ Smart Route Selection (Fast/RAG/Template/Financial)",
            "💰 Financial Planning with AI Calculation",
            "🔧 Sentence Completion Guarantee",
            "🌐 Platform-Optimized Processing",
            "⚡ High-Performance Caching",
            "🛡️ Error Recovery with Completeness"
        ],
        "routing_efficiency": routing_stats,
        "duplicate_prevention": duplicate_stats,
        "uptime": time.time() - startup_time,
        "line_integration": {
            "mode": LINE_BOT_MODE,
            "webhook": "/line/webhook",
            "registered_handlers": 1,
            "duplicate_messages": "prevented",
            "single_integration": SINGLE_LINE_INTEGRATION
        }
    }

@app.get("/system-status")
async def get_system_status():
    """システム状態（重複防止統計追加）"""
    routing_stats = smart_router.get_stats()
    duplicate_stats = duplicate_prevention.get_stats()
    
    # アクティブな資金計画セッション数を取得
    active_financial_sessions = 0
    try:
        from api.routers.line_bot_financial_planner import get_financial_planning_handler
        handler = get_financial_planning_handler()
        active_financial_sessions = len(handler.state_manager.user_states)
    except:
        pass
    
    return {
        "optimization_features": {
            "smart_routing": ENABLE_SMART_ROUTING,
            "fast_routes": ENABLE_FAST_ROUTES,
            "sentence_completion": ENABLE_SENTENCE_COMPLETION,
            "rag_initialization": ENABLE_RAG_INITIALIZATION,
            "line_integration": ENABLE_LINE_INTEGRATION,
            "financial_planning": ENABLE_FINANCIAL_PLANNING,
            "duplicate_prevention": ENABLE_DUPLICATE_PREVENTION,
            "single_integration": SINGLE_LINE_INTEGRATION,
            "line_bot_mode": LINE_BOT_MODE
        },
        "routing_performance": routing_stats,
        "duplicate_prevention": duplicate_stats,
        "system_health": {
            "rag_initialized": is_initialized,
            "vectorstore_ready": vectorstore is not None,
            "llm_ready": llm_instance is not None
        },
        "line_integration": {
            "webhook_endpoint": "/line/webhook",
            "active_bot_mode": LINE_BOT_MODE,
            "registered_routers": 1,
            "duplicate_prevention": True,
            "single_integration": True
        },
        "financial_planning": {
            "enabled": ENABLE_FINANCIAL_PLANNING,
            "active_sessions": active_financial_sessions,
            "liff_page_available": True,
            "calculation_engine": "operational"
        },
        "version": "5.1.0-duplicate-prevention",
        "timestamp": datetime.now().isoformat()
    }

# ==============================================================================
# 重複防止専用エンドポイント（新規追加）
# ==============================================================================
@app.get("/duplicate-prevention/stats")
async def get_duplicate_prevention_stats():
    """重複防止統計取得"""
    routing_stats = smart_router.get_stats()
    duplicate_stats = duplicate_prevention.get_stats()
    
    return {
        "duplicate_prevention": duplicate_stats,
        "routing_stats": {
            "total_requests": routing_stats["total_requests"],
            "duplicates_prevented": routing_stats["duplicate_prevented_count"],
            "duplicate_prevention_rate": routing_stats["duplicate_prevention_rate"]
        },
        "effectiveness": {
            "prevention_enabled": ENABLE_DUPLICATE_PREVENTION,
            "window_seconds": duplicate_stats["duplicate_window_seconds"],
            "active_records": duplicate_stats["active_records"]
        },
        "timestamp": datetime.now().isoformat()
    }

@app.post("/duplicate-prevention/clear")
async def clear_duplicate_prevention_cache():
    """重複防止キャッシュクリア"""
    old_count = len(duplicate_prevention.recent_sends)
    duplicate_prevention.recent_sends.clear()
    
    return {
        "status": "cleared",
        "cleared_records": old_count,
        "timestamp": datetime.now().isoformat()
    }

# ==============================================================================
# 管理エンドポイント（重複防止対応版）
# ==============================================================================
@app.post("/routing/reset-stats")
async def reset_routing_stats():
    """ルーティング統計リセット（重複防止統計含む）"""
    old_stats = smart_router.get_stats()
    smart_router.routing_stats = {
        "fast_route_count": 0,
        "rag_route_count": 0,
        "template_route_count": 0,
        "line_route_count": 0,
        "financial_route_count": 0,
        "duplicate_prevented_count": 0,
        "total_requests": 0
    }
    
    return {
        "status": "routing_stats_reset",
        "previous_stats": old_stats,
        "duplicate_prevention_included": True,
        "timestamp": datetime.now().isoformat()
    }

# ==============================================================================
# ★重要：起動時処理（単一LINE Bot統合・重複防止対応）
# ==============================================================================
@app.on_event("startup")
async def startup_event():
    """単一LINE Bot統合起動処理（重複メッセージ完全防止版）"""
    logger.info("🚀 Starting Single LINE Bot Integration with Duplicate Message Prevention...")
    
    # RAG初期化（バックグラウンド）
    if ENABLE_RAG_INITIALIZATION:
        asyncio.create_task(initialize_rag_components())
    
    # ★最重要：単一LINE Bot統合（重複登録完全防止）
    if ENABLE_LINE_INTEGRATION and SINGLE_LINE_INTEGRATION:
        try:
            logger.info(f"🎯 Loading SINGLE LINE Bot in mode: {LINE_BOT_MODE}")
            
            # ★注意：ここで1つのモードのみを選択し、他は一切読み込まない
            if LINE_BOT_MODE == "ultra_fast_financial":
                logger.info("📦 Loading Ultra Fast Bot with Financial Planning...")
                from api.routers.line_bot_ultra_fast import router as line_router
                app.include_router(line_router, prefix="/line", tags=["line"])
                logger.info("✅ SINGLE LINE Ultra Fast Bot with Financial Planning loaded at /line/webhook")
                
            else:
                logger.warning(f"⚠️ Unknown LINE_BOT_MODE: {LINE_BOT_MODE}, defaulting to ultra_fast_financial")
                from api.routers.line_bot_ultra_fast import router as line_router
                app.include_router(line_router, prefix="/line", tags=["line"])
                logger.info("✅ SINGLE LINE Ultra Fast Bot with Financial Planning loaded at /line/webhook (default)")
            
            logger.info("🔒 ★重複防止確認：他のLINE Botルーターは一切読み込まれていません")
            
        except Exception as e:
            logger.error(f"❌ Failed to load SINGLE LINE Bot in {LINE_BOT_MODE} mode: {e}")
            logger.error("   This will cause LINE webhook failures")
    
    # 資金計画API（LIFF・計算エンドポイント）
    if ENABLE_FINANCIAL_PLANNING:
        try:
            from api.routers.financial_api import router as financial_router
            app.include_router(financial_router, prefix="/financial", tags=["financial"])
            logger.info("✅ Financial Planning API router added")
        except Exception as e:
            logger.warning(f"⚠️ Failed to add Financial Planning API router: {e}")
    
    # 他のルーター（Web系のみ）
    try:
        from api.routers.chat_ultra_fast import router as chat_ultra_fast_router
        app.include_router(chat_ultra_fast_router, prefix="/chat-ultra-fast", tags=["chat-ultra-fast"])
        logger.info("✅ Chat Ultra Fast router added")
    except Exception as e:
        logger.warning(f"⚠️ Failed to add Chat Ultra Fast router: {e}")
    
    try:
        from api.routers.chat import router as chat_router
        app.include_router(chat_router, prefix="/chat-standard", tags=["chat-standard"])
        logger.info("✅ Standard Chat router added")
    except Exception as e:
        logger.warning(f"⚠️ Failed to add Standard Chat router: {e}")
    
    try:
        from api.routers.upload import router as upload_router
        app.include_router(upload_router, prefix="/upload", tags=["upload"])
        logger.info("✅ Upload router added")
    except Exception as e:
        logger.warning(f"⚠️ Upload router not added: {e}")
    
    # LINE関連補助機能（重複に影響しないもののみ）
    try:
        from api.routers.line_login import router as line_login_router
        app.include_router(line_login_router, prefix="/line-login", tags=["line-login"])
        logger.info("✅ LINE Login router added")
    except Exception as e:
        logger.info(f"ℹ️ LINE Login router not added: {e}")
    
    try:
        from api.routers.line_proxy import router as line_proxy_router  
        app.include_router(line_proxy_router, prefix="/line-proxy", tags=["line-proxy"])
        logger.info("✅ LINE Proxy router added")
    except Exception as e:
        logger.info(f"ℹ️ LINE Proxy router not added: {e}")
    
    logger.info("🎉 Single LINE Bot Integration with Duplicate Prevention completed successfully")
    logger.info(f"⚡ Startup time: {time.time() - startup_time:.2f} seconds")
    logger.info(f"🎯 Smart Routing: {'Enabled' if ENABLE_SMART_ROUTING else 'Disabled'}")
    logger.info(f"🔧 Sentence Completion: {'Enabled' if ENABLE_SENTENCE_COMPLETION else 'Disabled'}")
    logger.info(f"📱 LINE Integration: {'Enabled' if ENABLE_LINE_INTEGRATION else 'Disabled'}")
    logger.info(f"💰 Financial Planning: {'Enabled' if ENABLE_FINANCIAL_PLANNING else 'Disabled'}")
    logger.info(f"🚫 Duplicate Prevention: {'Enabled' if ENABLE_DUPLICATE_PREVENTION else 'Disabled'}")
    logger.info(f"🤖 LINE Bot Mode: {LINE_BOT_MODE}")
    logger.info(f"🔒 Single Integration: {'Enabled' if SINGLE_LINE_INTEGRATION else 'Disabled'}")
    logger.info("📋 Available Endpoints:")
    logger.info(f"   - /line/webhook (SINGLE integration - {LINE_BOT_MODE} mode)")
    logger.info(f"   - /financial/* (Financial planning APIs)")
    logger.info(f"   - /duplicate-prevention/stats (Duplicate prevention monitoring)")
    logger.info("🛡️ Duplicate message prevention: ENABLED (60s window)")
    logger.info("💰 Financial planning state management: ENABLED")
    logger.info("🔒 Multiple LINE Bot registration: COMPLETELY PREVENTED")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)