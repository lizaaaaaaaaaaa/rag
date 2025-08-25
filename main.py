# main.py - 資金計画機能統合版（LINE Bot単一統合完全修正版）

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
    title="RAG API - LINE Bot with Financial Planning Integration",
    description="High-Performance AI Chat API with LINE Bot Financial Planning (Single Integration - No Duplicates)",
    version="5.0.0-financial"
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

# 設定フラグ（資金計画機能追加）
ENABLE_RAG_INITIALIZATION = True
ENABLE_SMART_ROUTING = True
ENABLE_FAST_ROUTES = True
ENABLE_SENTENCE_COMPLETION = True
ENABLE_LINE_INTEGRATION = True  # LINE統合を有効化
ENABLE_FINANCIAL_PLANNING = True  # 🆕 資金計画機能を有効化

# LINE統合設定（★重要：複数ルーター問題解決 + 資金計画統合）
LINE_BOT_MODE = os.getenv("LINE_BOT_MODE", "ultra_fast_financial")  # 🆕 新モード追加

# ==============================================================================
# 拡張スマートルーティングシステム（資金計画統合版）
# ==============================================================================
class SmartRouterWithFinancial:
    """用途別ルート振り分けシステム（資金計画統合版）"""
    
    def __init__(self):
        self.routing_stats = {
            "fast_route_count": 0,
            "rag_route_count": 0, 
            "template_route_count": 0,
            "line_route_count": 0,
            "financial_route_count": 0,  # 🆕 資金計画ルート統計
            "total_requests": 0
        }
        
        # 高速ルート対象キーワード（LINE最適化）
        self.fast_keywords = [
            "AI相談", "資料請求", "展示場", "見学", "予約", "チャット相談",
            "AI住まいサイト", "サイト", "ホームページ",
            "こんにちは", "はじめまして", "よろしく", "ありがとう", "お疲れ様",
            "友だち追加", "登録", "メニュー", "ボタン", "タップ"
        ]
        
        # 🆕 資金計画専用キーワード
        self.financial_keywords = [
            "資金計画", "💰", "ローン計算", "予算診断", "支払い診断",
            "年収", "返済", "借入期間", "家族構成", "負担", "車ローン",
            "毎月", "万円", "金利", "頭金", "ボーナス"
        ]
        
        # RAG処理が必要なキーワード（専門知識必要）
        self.rag_keywords = [
            "坪単価", "価格", "費用", "金額", "コスト", "値段", "見積り",
            "仕様", "標準", "設備", "グレード", "オプション", "間取り",
            "断熱", "性能", "省エネ", "ZEH", "UA値", "C値", "気密",
            "耐震", "地震", "安全", "構造", "基礎", "工法", "強度",
            "補助金", "助成金", "支援金", "制度", "控除", "減税",
            "建ぺい率", "容積率", "法規", "規制", "基準", "建築基準法"
        ]
        
        # LINE専用高速処理キーワード
        self.line_instant_keywords = [
            "ai相談", "資料請求", "展示場予約", "チャット相談", "ai住まいサイト"
        ]
        
        # 🆕 資金計画状態管理フラグ
        self.financial_sessions = {}  # user_id -> session_info
    
    def determine_route(self, query: str, platform: str = "web", user_id: str = None) -> str:
        """クエリに基づく最適ルート決定（資金計画統合版）"""
        self.routing_stats["total_requests"] += 1
        query_lower = query.lower()
        
        # 🆕 資金計画セッション状態チェック（最優先）
        if user_id and ENABLE_FINANCIAL_PLANNING:
            # アクティブな資金計画セッションがある場合
            if self._has_active_financial_session(user_id):
                self.routing_stats["financial_route_count"] += 1
                return "financial_session"
            
            # 新規資金計画開始チェック
            if any(keyword in query_lower for keyword in self.financial_keywords):
                self.routing_stats["financial_route_count"] += 1
                return "financial_start"
        
        # LINE特有の処理
        if platform == "line":
            self.routing_stats["line_route_count"] += 1
            
            # 1. LINE即座応答チェック（最優先）
            if any(keyword in query_lower for keyword in self.line_instant_keywords):
                self.routing_stats["fast_route_count"] += 1
                return "line_instant"
            
            # 2. 短いメッセージはテンプレート（LINE特化）
            if len(query) <= 10:
                self.routing_stats["template_route_count"] += 1
                return "line_template"
        
        # 1. 高速ルート判定（テンプレート対応可能）
        if any(keyword in query_lower for keyword in self.fast_keywords):
            self.routing_stats["fast_route_count"] += 1
            return "fast"
        
        # 2. RAGルート判定（専門知識が必要）
        if any(keyword in query_lower for keyword in self.rag_keywords):
            self.routing_stats["rag_route_count"] += 1
            return "rag"
        
        # 3. 質問の複雑さで判定
        question_indicators = ["？", "?", "教えて", "知りたい", "どう", "なぜ", "どこ", "いつ"]
        if any(indicator in query for indicator in question_indicators):
            # 複雑な質問はRAGへ
            if len(query) > 20:
                self.routing_stats["rag_route_count"] += 1
                return "rag"
            else:
                self.routing_stats["fast_route_count"] += 1
                return "fast"
        
        # 4. デフォルト：短い文章は高速、長い文章はRAG
        if len(query) <= 15:
            self.routing_stats["template_route_count"] += 1
            return "template"
        else:
            self.routing_stats["rag_route_count"] += 1
            return "rag"
    
    def _has_active_financial_session(self, user_id: str) -> bool:
        """アクティブな資金計画セッションがあるかチェック"""
        try:
            # 資金計画ハンドラーから状態を確認
            from api.routers.line_bot_financial_planner import get_financial_planning_handler
            handler = get_financial_planning_handler()
            session = handler.state_manager.get_session(user_id)
            return session is not None
        except:
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        """ルーティング統計取得（資金計画統計追加）"""
        total = self.routing_stats["total_requests"]
        
        return {
            "total_requests": total,
            "fast_route_percentage": (self.routing_stats["fast_route_count"] / total * 100) if total > 0 else 0,
            "rag_route_percentage": (self.routing_stats["rag_route_count"] / total * 100) if total > 0 else 0,
            "template_route_percentage": (self.routing_stats["template_route_count"] / total * 100) if total > 0 else 0,
            "line_route_percentage": (self.routing_stats["line_route_count"] / total * 100) if total > 0 else 0,
            "financial_route_percentage": (self.routing_stats["financial_route_count"] / total * 100) if total > 0 else 0,  # 🆕
            "routing_efficiency": {
                "fast_routes": self.routing_stats["fast_route_count"],
                "rag_routes": self.routing_stats["rag_route_count"],
                "template_routes": self.routing_stats["template_route_count"],
                "line_routes": self.routing_stats["line_route_count"],
                "financial_routes": self.routing_stats["financial_route_count"]  # 🆕
            }
        }

# グローバルルーター（資金計画統合版）
smart_router = SmartRouterWithFinancial()

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
            # LINE用補完（絵文字・短文・親しみやすい）
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
            # Web用補完（シンプル・丁寧）
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
            # パターンにマッチしない場合の処理
            if text.endswith(('ます', 'です')):
                text += '。'
            elif text.endswith(('た', 'る', 'し')):
                text += '。'
            elif text.endswith(('は', 'が')):
                text += '重要なポイントです。'
            elif text.endswith(('選定', '検討', '確認', '準備', '計画', '設計')):
                text += 'も大切です。'
            else:
                # 長さによる補完
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
    """プラットフォーム別フォールバック応答（資金計画対応版）"""
    
    # 🆕 資金計画関連キーワードチェック
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
# RAGコンポーネント初期化（非同期最適化版）
# ==============================================================================
async def initialize_rag_components():
    """RAGコンポーネントの非同期初期化"""
    global vectorstore, rag_chain_template, llm_instance, is_initialized
    
    if is_initialized:
        return
    
    async with initialization_lock:
        if is_initialized:
            return
            
        logger.info("🚀 Initializing optimized RAG components with financial planning (async)...")
        
        try:
            # LLMインスタンス（文章完全性対応版）
            from llm.llm_runner import load_llm
            llm_instance = load_llm()[0]
            logger.info("✅ LLM instance loaded")
            
            # ベクトルストア読み込み
            try:
                from rag.fast_rag_chain import load_ultra_fast_vectorstore, get_ultra_fast_rag_chain
                vectorstore = load_ultra_fast_vectorstore()
                rag_chain_template = get_ultra_fast_rag_chain(vectorstore)
                logger.info("✅ Ultra fast RAG chain loaded")
            except Exception as e:
                logger.warning(f"⚠️ Ultra fast RAG chain failed, using fallback: {e}")
                # フォールバック処理はそのまま
            
            is_initialized = True
            logger.info("✅ Optimized RAG components with financial planning initialized successfully")
            
        except Exception as e:
            logger.error(f"❌ RAG initialization failed: {e}")
            is_initialized = False

# ==============================================================================
# リクエストモデル（資金計画対応版）
# ==============================================================================
class OptimizedChatRequest(BaseModel):
    question: str
    username: str | None = None
    platform: str | None = "web"
    route_preference: str | None = None
    financial_context: Dict[str, Any] | None = None  # 🆕 資金計画コンテキスト

# ==============================================================================
# エンドポイント（資金計画対応版）
# ==============================================================================
@app.post("/chat")
@app.post("/chat/")
async def optimized_chat_endpoint(req: OptimizedChatRequest, request: Request):
    """最適化チャットエンドポイント（資金計画対応強化版）"""
    
    overall_start = time.time()
    platform = req.platform or "web"
    username = req.username or f"{platform}-user"
    
    logger.info(f"🌐 Optimized Chat with Financial ({platform}): {req.question[:50]}...")
    
    try:
        # 1. スマートルーティング（資金計画統合版）
        if req.route_preference and req.route_preference in ["fast", "rag", "line_instant", "financial"]:
            selected_route = req.route_preference
            logger.info(f"🎯 User-specified route: {selected_route}")
        else:
            selected_route = smart_router.determine_route(req.question, platform, username)
            logger.info(f"🧠 Smart-selected route: {selected_route}")
        
        # 2. ルート別処理（資金計画ルート追加）
        if selected_route in ["financial_start", "financial_session"]:
            # 🆕 資金計画ルート
            response = await process_financial_route(req.question, username, req.financial_context)
            
        elif selected_route == "line_instant":
            # LINE即座応答ルート
            response = await process_line_instant_route(req.question, username)
            
        elif selected_route == "line_template":
            # LINEテンプレートルート
            response = await process_line_template_route(req.question, username)
            
        elif selected_route == "fast" and ENABLE_FAST_ROUTES:
            # 高速ルート（テンプレート + 軽量処理）
            response = await process_fast_route(req.question, platform, username)
            
        elif selected_route == "rag":
            # RAGルート（高品質回答）
            response = await process_rag_route(req.question, platform, username)
            
        else:
            # テンプレートルート（即座応答）
            response = await process_template_route(req.question, platform, username)
        
        total_time = time.time() - overall_start
        
        # 3. 文章完全性チェック（プラットフォーム最適化）
        if ENABLE_SENTENCE_COMPLETION:
            response["answer"] = ensure_response_completeness(
                response["answer"], req.question, platform
            )
            response["sentence_complete"] = response["answer"].endswith(('。', '！', '？', '.', '!', '?'))
        
        logger.info(f"✅ Optimized Response with Financial ({platform}): {total_time:.3f}s, "
                   f"route={selected_route}, "
                   f"length={len(response['answer'])}, "
                   f"complete={response.get('sentence_complete', False)}")
        
        return {
            "answer": response["answer"],
            "sources": response.get("sources", []),
            "status": response.get("status", "ok"),
            "financial_data": response.get("financial_data"),  # 🆕 資金計画データ
            "performance": {
                "total_time": total_time,
                "selected_route": selected_route,
                "platform": platform,
                "sentence_complete": response.get("sentence_complete", False),
                "smart_routing_enabled": ENABLE_SMART_ROUTING,
                "financial_planning_enabled": ENABLE_FINANCIAL_PLANNING,  # 🆕
                "processing_method": response.get("method", "unknown")
            }
        }
        
    except Exception as e:
        total_time = time.time() - overall_start
        error_id = str(uuid4())[:8]
        
        logger.error(f"❌ Optimized chat with financial error [{error_id}]: {e}")
        logger.error(traceback.format_exc())
        
        # エラー時も文章完全性保証
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
# ルート処理関数（資金計画ルート追加）
# ==============================================================================
async def process_financial_route(query: str, username: str, financial_context: Optional[Dict] = None) -> Dict[str, Any]:
    """🆕 資金計画ルート処理"""
    try:
        from api.routers.line_bot_financial_planner import handle_financial_message_for_line
        
        # 資金計画処理実行
        result = handle_financial_message_for_line(username, query)
        
        return {
            "answer": result,
            "sources": [],
            "status": "ok",
            "method": "financial_planning",
            "financial_data": financial_context
        }
        
    except Exception as e:
        logger.error(f"Financial route error: {e}")
        return {
            "answer": generate_platform_fallback(query, "line"),
            "sources": [],
            "status": "fallback",
            "method": "financial_fallback",
            "financial_data": None
        }

async def process_line_instant_route(query: str, username: str) -> Dict[str, Any]:
    """LINE即座応答ルート処理"""
    return {
        "answer": generate_platform_fallback(query, "line"),
        "sources": [],
        "status": "ok",
        "method": "line_instant"
    }

async def process_line_template_route(query: str, username: str) -> Dict[str, Any]:
    """LINEテンプレートルート処理"""
    return {
        "answer": generate_platform_fallback(query, "line"),
        "sources": [],
        "status": "ok",
        "method": "line_template"
    }

async def process_fast_route(query: str, platform: str, username: str) -> Dict[str, Any]:
    """高速ルート処理"""
    try:
        if platform == "line":
            # LINE用高速処理は統合LINE Botで処理されるためここでは基本応答
            return {
                "answer": generate_platform_fallback(query, platform),
                "sources": [],
                "status": "ok",
                "method": "line_basic"
            }
        else:
            # Web用高速処理
            from api.routers.chat_ultra_fast import separated_generator
            result = await separated_generator.generate_separated_response(query, platform, username)
            
            return {
                "answer": result["answer"],
                "sources": [],
                "status": result.get("status", "ok"),
                "method": "web_ultra_fast"
            }
            
    except Exception as e:
        logger.error(f"Fast route error: {e}")
        return {
            "answer": generate_platform_fallback(query, platform),
            "sources": [],
            "status": "fallback",
            "method": "fast_fallback"
        }

async def process_rag_route(query: str, platform: str, username: str) -> Dict[str, Any]:
    """RAGルート処理"""
    try:
        # RAG初期化確認
        if not is_initialized and ENABLE_RAG_INITIALIZATION:
            await initialize_rag_components()
        
        if rag_chain_template:
            # RAG処理実行
            result = rag_chain_template.invoke({"query": query})
            rag_answer = result.get("result", "")
            
            if rag_answer and len(rag_answer.strip()) > 10:
                return {
                    "answer": rag_answer,
                    "sources": [],
                    "status": "ok",
                    "method": "rag_processing"
                }
        
        # RAG失敗時のフォールバック
        return {
            "answer": generate_platform_fallback(query, platform),
            "sources": [],
            "status": "fallback",
            "method": "rag_fallback"
        }
        
    except Exception as e:
        logger.error(f"RAG route error: {e}")
        return {
            "answer": generate_platform_fallback(query, platform),
            "sources": [],
            "status": "fallback",
            "method": "rag_error_fallback"
        }

async def process_template_route(query: str, platform: str, username: str) -> Dict[str, Any]:
    """テンプレートルート処理"""
    return {
        "answer": generate_platform_fallback(query, platform),
        "sources": [],
        "status": "ok",
        "method": "template_direct"
    }

# ==============================================================================
# ヘルスチェック・システム状態（資金計画統合版）
# ==============================================================================
@app.get("/healthz")
async def health_check():
    """最適化ヘルスチェック（資金計画統合版）"""
    uptime = time.time() - startup_time
    routing_stats = smart_router.get_stats()
    
    return {
        "status": "healthy",
        "uptime": uptime,
        "timestamp": datetime.now().isoformat(),
        "version": "5.0.0-financial-integration",
        "message": "Optimized RAG API with LINE Bot Financial Planning Integration (Single - No Duplicates)",
        "features": {
            "smart_routing": ENABLE_SMART_ROUTING,
            "fast_routes": ENABLE_FAST_ROUTES,
            "sentence_completion": ENABLE_SENTENCE_COMPLETION,
            "rag_initialization": ENABLE_RAG_INITIALIZATION,
            "line_integration": ENABLE_LINE_INTEGRATION,
            "financial_planning": ENABLE_FINANCIAL_PLANNING,  # 🆕
            "line_bot_mode": LINE_BOT_MODE
        },
        "routing_stats": routing_stats,
        "rag_status": {
            "initialized": is_initialized,
            "vectorstore_ready": vectorstore is not None,
            "llm_ready": llm_instance is not None
        },
        "line_status": {
            "single_webhook_mode": True,
            "active_bot_mode": LINE_BOT_MODE,
            "webhook_endpoint": "/line/webhook",
            "duplicate_prevention": "enabled",
            "financial_integration": ENABLE_FINANCIAL_PLANNING  # 🆕
        }
    }

@app.get("/")
async def root():
    """ルートエンドポイント（資金計画機能追加版）"""
    routing_stats = smart_router.get_stats()
    
    return {
        "message": "Optimized RAG API with LINE Bot Financial Planning Integration (Single - No Duplicate Messages)",
        "version": "5.0.0-financial",
        "timestamp": datetime.now().isoformat(),
        "features": [
            "Smart Route Selection (Fast/RAG/Template/LINE/Financial)",
            "Single LINE Bot Integration (No Duplicates)", 
            "Financial Planning with AI Calculation",  # 🆕
            "Sentence Completion Guarantee", 
            "Platform-Optimized Processing",
            "LLM/OpenAI API Independence (Fast Routes)",
            "High-Performance Caching",
            "Error Recovery with Completeness",
            "LIFF Integration for Financial Planning"  # 🆕
        ],
        "routing_efficiency": routing_stats,
        "uptime": time.time() - startup_time,
        "line_integration": {
            "mode": LINE_BOT_MODE,
            "webhook": "/line/webhook",
            "duplicate_messages": "prevented",
            "financial_planning": "integrated"  # 🆕
        }
    }

@app.get("/system-status")
async def get_system_status():
    """最適化システム状態（資金計画統合版）"""
    routing_stats = smart_router.get_stats()
    
    # 🆕 アクティブな資金計画セッション数を取得
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
            "financial_planning": ENABLE_FINANCIAL_PLANNING,  # 🆕
            "line_bot_mode": LINE_BOT_MODE
        },
        "routing_performance": routing_stats,
        "system_health": {
            "rag_initialized": is_initialized,
            "vectorstore_ready": vectorstore is not None,
            "llm_ready": llm_instance is not None
        },
        "line_integration": {
            "webhook_endpoint": "/line/webhook",
            "active_bot_mode": LINE_BOT_MODE,
            "registered_routers": 1,  # 単一統合
            "duplicate_prevention": True,
            "financial_integration": True  # 🆕
        },
        "financial_planning": {  # 🆕 資金計画統計
            "enabled": ENABLE_FINANCIAL_PLANNING,
            "active_sessions": active_financial_sessions,
            "liff_page_available": True,
            "calculation_engine": "operational"
        },
        "completion_patterns": 20,
        "supported_platforms": ["web", "line"],
        "version": "5.0.0-financial-integration",
        "timestamp": datetime.now().isoformat()
    }

# ==============================================================================
# 管理エンドポイント（資金計画対応版）
# ==============================================================================
@app.post("/routing/reset-stats")
async def reset_routing_stats():
    """ルーティング統計リセット（資金計画統計含む）"""
    old_stats = smart_router.get_stats()
    smart_router.routing_stats = {
        "fast_route_count": 0,
        "rag_route_count": 0,
        "template_route_count": 0,
        "line_route_count": 0,
        "financial_route_count": 0,  # 🆕
        "total_requests": 0
    }
    
    return {
        "status": "routing_stats_reset",
        "previous_stats": old_stats,
        "financial_stats_included": True,  # 🆕
        "timestamp": datetime.now().isoformat()
    }

@app.get("/routing/test/{query}")
async def test_routing(query: str, platform: str = "web", user_id: str = "test_user"):
    """ルーティングテスト（資金計画対応）"""
    selected_route = smart_router.determine_route(query, platform, user_id)
    
    return {
        "query": query,
        "platform": platform,
        "user_id": user_id,
        "selected_route": selected_route,
        "routing_logic": {
            "fast_keywords_matched": any(kw in query.lower() for kw in smart_router.fast_keywords),
            "rag_keywords_matched": any(kw in query.lower() for kw in smart_router.rag_keywords),
            "financial_keywords_matched": any(kw in query.lower() for kw in smart_router.financial_keywords),  # 🆕
            "line_instant_matched": any(kw in query.lower() for kw in smart_router.line_instant_keywords) if platform == "line" else False,
            "query_length": len(query),
            "has_active_financial_session": smart_router._has_active_financial_session(user_id)  # 🆕
        },
        "timestamp": datetime.now().isoformat()
    }

# ==============================================================================
# 🆕 資金計画専用管理エンドポイント
# ==============================================================================
@app.get("/financial/sessions")
async def get_financial_sessions():
    """アクティブな資金計画セッション一覧"""
    try:
        from api.routers.line_bot_financial_planner import get_financial_planning_handler
        handler = get_financial_planning_handler()
        
        sessions = []
        for user_id, session in handler.state_manager.user_states.items():
            sessions.append({
                "user_id": user_id,
                "completion_rate": session.get_completion_rate(),
                "missing_fields": session.get_missing_fields(),
                "created_at": session.created_at.isoformat(),
                "session_data": {
                    "annual_income": session.annual_income,
                    "monthly_payment": session.monthly_payment,
                    "loan_period": session.loan_period,
                    "family_composition": session.family_composition,
                    "other_expenses": session.other_expenses
                }
            })
        
        return {
            "active_sessions": len(sessions),
            "sessions": sessions,
            "session_timeout_hours": 2,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error getting financial sessions: {e}")
        return {
            "active_sessions": 0,
            "sessions": [],
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

@app.post("/financial/sessions/clear-all")
async def clear_all_financial_sessions():
    """全ての資金計画セッションをクリア"""
    try:
        from api.routers.line_bot_financial_planner import get_financial_planning_handler
        handler = get_financial_planning_handler()
        
        session_count = len(handler.state_manager.user_states)
        handler.state_manager.user_states.clear()
        
        return {
            "success": True,
            "cleared_sessions": session_count,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error clearing financial sessions: {e}")
        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

# ==============================================================================
# 起動時処理（★修正：資金計画統合LINE Bot登録）
# ==============================================================================
@app.on_event("startup")
async def startup_event():
    """資金計画統合LINE Bot起動処理（複数登録問題完全修正版）"""
    logger.info("🚀 Starting Optimized RAG API with LINE Bot Financial Planning Integration...")
    
    # RAG初期化（バックグラウンド）
    if ENABLE_RAG_INITIALIZATION:
        asyncio.create_task(initialize_rag_components())
    
    # ★重要：LINE Bot統合（資金計画機能統合・単一ルーター登録）
    if ENABLE_LINE_INTEGRATION:
        try:
            logger.info(f"🎯 Loading LINE Bot with Financial Planning in mode: {LINE_BOT_MODE}")
            
            # 選択されたモードに基づいて単一のLINE Botルーターを登録
            if LINE_BOT_MODE == "ultra_fast_financial":
                # 🆕 Ultra Fast + 資金計画統合モード（推奨）
                from api.routers.line_bot_ultra_fast import router as line_router
                app.include_router(line_router, prefix="/line", tags=["line"])
                logger.info("✅ LINE Ultra Fast Bot with Financial Planning loaded at /line/webhook")
                
            elif LINE_BOT_MODE == "ultra_fast":
                # Ultra Fastモード（従来版）
                from api.routers.line_bot_ultra_fast import router as line_router
                app.include_router(line_router, prefix="/line", tags=["line"])
                logger.info("✅ LINE Ultra Fast Bot loaded at /line/webhook")
                
            elif LINE_BOT_MODE == "rag_integrated":
                # RAG統合モード（高品質応答）
                from api.routers.line_bot_rag_integrated import router as line_router
                app.include_router(line_router, prefix="/line", tags=["line"])
                logger.info("✅ LINE RAG Integrated Bot loaded at /line/webhook")
                
            elif LINE_BOT_MODE == "template_only":
                # テンプレートオンリーモード（超高速）
                from api.routers.line_bot_template_fast import router as line_router
                app.include_router(line_router, prefix="/line", tags=["line"])
                logger.info("✅ LINE Template Fast Bot loaded at /line/webhook")
                
            else:
                logger.warning(f"⚠️ Unknown LINE_BOT_MODE: {LINE_BOT_MODE}, defaulting to ultra_fast_financial")
                from api.routers.line_bot_ultra_fast import router as line_router
                app.include_router(line_router, prefix="/line", tags=["line"])
                logger.info("✅ LINE Ultra Fast Bot with Financial Planning loaded at /line/webhook (default)")
            
            logger.info("🔒 Multiple LINE Bot registration PREVENTED")
            
        except Exception as e:
            logger.error(f"❌ Failed to load LINE Bot in {LINE_BOT_MODE} mode: {e}")
            logger.error("   This will cause LINE webhook failures")
    
    # 🆕 資金計画API（LIFF・計算エンドポイント）
    if ENABLE_FINANCIAL_PLANNING:
        try:
            from api.routers.financial_api import router as financial_router
            app.include_router(financial_router, prefix="/financial", tags=["financial"])
            logger.info("✅ Financial Planning API router added")
        except Exception as e:
            logger.warning(f"⚠️ Failed to add Financial Planning API router: {e}")
    
    # 他のルーター（Web系）
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
    
    # LINE関連補助機能（非重複）
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
    
    logger.info("🎉 LINE Bot Financial Planning Integration completed successfully")
    logger.info(f"⚡ Startup time: {time.time() - startup_time:.2f} seconds")
    logger.info(f"🎯 Smart Routing: {'Enabled' if ENABLE_SMART_ROUTING else 'Disabled'}")
    logger.info(f"🔧 Sentence Completion: {'Enabled' if ENABLE_SENTENCE_COMPLETION else 'Disabled'}")
    logger.info(f"📱 LINE Integration: {'Enabled' if ENABLE_LINE_INTEGRATION else 'Disabled'}")
    logger.info(f"💰 Financial Planning: {'Enabled' if ENABLE_FINANCIAL_PLANNING else 'Disabled'}")
    logger.info(f"🤖 LINE Bot Mode: {LINE_BOT_MODE}")
    logger.info("📋 Available Endpoints:")
    logger.info(f"   - /line/webhook (Single integration - {LINE_BOT_MODE} mode)")
    logger.info(f"   - /financial/liff-page (LIFF資金計画ページ)")
    logger.info(f"   - /financial/calculate (資金計算API)")
    logger.info(f"   - /financial/sessions (セッション管理)")
    logger.info("🛡️ Duplicate message prevention: ENABLED")
    logger.info("💰 Financial planning state management: ENABLED")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)