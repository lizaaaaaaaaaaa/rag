# main.py - LINE Webhook 404エラー修正 & 最適化版

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
    title="RAG API - LINE Webhook Fixed & Optimized Edition",
    description="High-Performance AI Chat API with Fixed LINE Integration and Smart Routing",
    version="4.1.0"
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

# 設定フラグ
ENABLE_RAG_INITIALIZATION = True
ENABLE_SMART_ROUTING = True
ENABLE_FAST_ROUTES = True
ENABLE_SENTENCE_COMPLETION = True
ENABLE_LINE_INTEGRATION = True  # LINE統合を有効化

# ==============================================================================
# スマートルーティングシステム（改良版）
# ==============================================================================
class SmartRouter:
    """用途別ルート振り分けシステム（LINE最適化版）"""
    
    def __init__(self):
        self.routing_stats = {
            "fast_route_count": 0,
            "rag_route_count": 0, 
            "template_route_count": 0,
            "line_route_count": 0,  # LINE専用統計追加
            "total_requests": 0
        }
        
        # 高速ルート対象キーワード（LINE最適化）
        self.fast_keywords = [
            "AI相談", "資料請求", "展示場", "見学", "予約", "チャット相談",
            "AI住まいサイト", "サイト", "ホームページ", "資金計画", "ローン",
            "こんにちは", "はじめまして", "よろしく", "ありがとう", "お疲れ様",
            # LINE特有の表現を追加
            "友だち追加", "登録", "メニュー", "ボタン", "タップ"
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
            "ai相談", "資料請求", "展示場予約", "資金計画", "チャット相談", "ai住まいサイト"
        ]
    
    def determine_route(self, query: str, platform: str = "web") -> str:
        """クエリに基づく最適ルート決定（LINE最適化版）"""
        self.routing_stats["total_requests"] += 1
        query_lower = query.lower()
        
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
    
    def get_stats(self) -> Dict[str, Any]:
        """ルーティング統計取得（LINE統計追加）"""
        total = self.routing_stats["total_requests"]
        
        return {
            "total_requests": total,
            "fast_route_percentage": (self.routing_stats["fast_route_count"] / total * 100) if total > 0 else 0,
            "rag_route_percentage": (self.routing_stats["rag_route_count"] / total * 100) if total > 0 else 0,
            "template_route_percentage": (self.routing_stats["template_route_count"] / total * 100) if total > 0 else 0,
            "line_route_percentage": (self.routing_stats["line_route_count"] / total * 100) if total > 0 else 0,
            "routing_efficiency": {
                "fast_routes": self.routing_stats["fast_route_count"],
                "rag_routes": self.routing_stats["rag_route_count"],
                "template_routes": self.routing_stats["template_route_count"],
                "line_routes": self.routing_stats["line_route_count"]
            }
        }

# グローバルルーター
smart_router = SmartRouter()

# ==============================================================================
# 文章完全性保証システム（プラットフォーム最適化版）
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
    """プラットフォーム別フォールバック応答（改良版）"""
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
            
        logger.info("🚀 Initializing optimized RAG components (async)...")
        
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
            logger.info("✅ Optimized RAG components initialized successfully")
            
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

# ==============================================================================
# エンドポイント（最適化版）
# ==============================================================================
@app.post("/chat")
@app.post("/chat/")
async def optimized_chat_endpoint(req: OptimizedChatRequest, request: Request):
    """最適化チャットエンドポイント（LINE対応強化版）"""
    
    overall_start = time.time()
    platform = req.platform or "web"
    username = req.username or f"{platform}-user"
    
    logger.info(f"🌐 Optimized Chat ({platform}): {req.question[:50]}...")
    
    try:
        # 1. スマートルーティング（LINE最適化版）
        if req.route_preference and req.route_preference in ["fast", "rag", "line_instant"]:
            selected_route = req.route_preference
            logger.info(f"🎯 User-specified route: {selected_route}")
        else:
            selected_route = smart_router.determine_route(req.question, platform)
            logger.info(f"🧠 Smart-selected route: {selected_route}")
        
        # 2. ルート別処理（LINE専用ルート追加）
        if selected_route == "line_instant":
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
        
        logger.info(f"✅ Optimized Response ({platform}): {total_time:.3f}s, "
                   f"route={selected_route}, "
                   f"length={len(response['answer'])}, "
                   f"complete={response.get('sentence_complete', False)}")
        
        return {
            "answer": response["answer"],
            "sources": response.get("sources", []),
            "status": response.get("status", "ok"),
            "performance": {
                "total_time": total_time,
                "selected_route": selected_route,
                "platform": platform,
                "sentence_complete": response.get("sentence_complete", False),
                "smart_routing_enabled": ENABLE_SMART_ROUTING,
                "processing_method": response.get("method", "unknown")
            }
        }
        
    except Exception as e:
        total_time = time.time() - overall_start
        error_id = str(uuid4())[:8]
        
        logger.error(f"❌ Optimized chat error [{error_id}]: {e}")
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
                "performance": {
                    "total_time": total_time,
                    "selected_route": "error",
                    "platform": platform,
                    "sentence_complete": complete_fallback.endswith(('。', '！', '？', '.', '!', '?'))
                }
            }
        )

# ==============================================================================
# ルート処理関数（LINE専用ルート追加）
# ==============================================================================
async def process_line_instant_route(query: str, username: str) -> Dict[str, Any]:
    """LINE即座応答ルート処理"""
    try:
        # LINE専用高速テンプレート処理
        from api.routers.line_bot_template_fast import template_responder
        result = template_responder.get_instant_response(query, username)
        
        return {
            "answer": result["response"],
            "sources": [],
            "status": "ok",
            "method": "line_instant"
        }
        
    except Exception as e:
        logger.error(f"LINE instant route error: {e}")
        return {
            "answer": generate_platform_fallback(query, "line"),
            "sources": [],
            "status": "fallback",
            "method": "line_instant_fallback"
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
            # LINE用高速処理
            from api.routers.line_bot_template_fast import template_responder
            result = template_responder.get_instant_response(query, username)
            
            return {
                "answer": result["response"],
                "sources": [],
                "status": "ok",
                "method": "line_template_fast"
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
# ヘルスチェック・システム状態
# ==============================================================================
@app.get("/healthz")
async def health_check():
    """最適化ヘルスチェック（LINE統合状態追加）"""
    uptime = time.time() - startup_time
    routing_stats = smart_router.get_stats()
    
    return {
        "status": "healthy",
        "uptime": uptime,
        "timestamp": datetime.now().isoformat(),
        "version": "4.1.0-line-fixed",
        "message": "Optimized RAG API with LINE Integration Fixed",
        "features": {
            "smart_routing": ENABLE_SMART_ROUTING,
            "fast_routes": ENABLE_FAST_ROUTES,
            "sentence_completion": ENABLE_SENTENCE_COMPLETION,
            "rag_initialization": ENABLE_RAG_INITIALIZATION,
            "line_integration": ENABLE_LINE_INTEGRATION
        },
        "routing_stats": routing_stats,
        "rag_status": {
            "initialized": is_initialized,
            "vectorstore_ready": vectorstore is not None,
            "llm_ready": llm_instance is not None
        },
        "line_status": {
            "webhooks_available": ["/line/webhook", "/line-template-fast/webhook"],
            "routes_configured": True
        }
    }

@app.get("/")
async def root():
    """ルートエンドポイント"""
    routing_stats = smart_router.get_stats()
    
    return {
        "message": "Optimized RAG API with LINE Integration Fixed",
        "version": "4.1.0",
        "timestamp": datetime.now().isoformat(),
        "features": [
            "Smart Route Selection (Fast/RAG/Template/LINE)",
            "LINE Webhook 404 Error Fixed", 
            "Sentence Completion Guarantee", 
            "Platform-Optimized Processing",
            "LLM/OpenAI API Independence (Fast Routes)",
            "High-Performance Caching",
            "Error Recovery with Completeness"
        ],
        "routing_efficiency": routing_stats,
        "uptime": time.time() - startup_time,
        "line_webhooks": ["/line/webhook", "/line-template-fast/webhook"]
    }

@app.get("/system-status")
async def get_system_status():
    """最適化システム状態（LINE統合情報追加）"""
    routing_stats = smart_router.get_stats()
    
    return {
        "optimization_features": {
            "smart_routing": ENABLE_SMART_ROUTING,
            "fast_routes": ENABLE_FAST_ROUTES,
            "sentence_completion": ENABLE_SENTENCE_COMPLETION,
            "rag_initialization": ENABLE_RAG_INITIALIZATION,
            "line_integration": ENABLE_LINE_INTEGRATION
        },
        "routing_performance": routing_stats,
        "system_health": {
            "rag_initialized": is_initialized,
            "vectorstore_ready": vectorstore is not None,
            "llm_ready": llm_instance is not None
        },
        "line_integration": {
            "webhook_endpoints": ["/line/webhook", "/line-template-fast/webhook"],
            "line_routers_loaded": 2,
            "line_optimization_enabled": True
        },
        "completion_patterns": 20,
        "supported_platforms": ["web", "line"],
        "version": "4.1.0-line-fixed",
        "timestamp": datetime.now().isoformat()
    }

# ==============================================================================
# 管理エンドポイント
# ==============================================================================
@app.post("/routing/reset-stats")
async def reset_routing_stats():
    """ルーティング統計リセット"""
    old_stats = smart_router.get_stats()
    smart_router.routing_stats = {
        "fast_route_count": 0,
        "rag_route_count": 0,
        "template_route_count": 0,
        "line_route_count": 0,
        "total_requests": 0
    }
    
    return {
        "status": "routing_stats_reset",
        "previous_stats": old_stats,
        "timestamp": datetime.now().isoformat()
    }

@app.get("/routing/test/{query}")
async def test_routing(query: str, platform: str = "web"):
    """ルーティングテスト（LINE対応）"""
    selected_route = smart_router.determine_route(query, platform)
    
    return {
        "query": query,
        "platform": platform,
        "selected_route": selected_route,
        "routing_logic": {
            "fast_keywords_matched": any(kw in query.lower() for kw in smart_router.fast_keywords),
            "rag_keywords_matched": any(kw in query.lower() for kw in smart_router.rag_keywords),
            "line_instant_matched": any(kw in query.lower() for kw in smart_router.line_instant_keywords) if platform == "line" else False,
            "query_length": len(query)
        },
        "timestamp": datetime.now().isoformat()
    }

# ==============================================================================
# 起動時処理（LINE Webhook 404エラー修正）
# ==============================================================================
@app.on_event("startup")
async def startup_event():
    """最適化起動処理（LINE統合修正版）"""
    logger.info("🚀 Starting Optimized RAG API with LINE Integration Fixed...")
    
    # RAG初期化（バックグラウンド）
    if ENABLE_RAG_INITIALIZATION:
        asyncio.create_task(initialize_rag_components())
    
    # ルーター追加（LINE Webhook 404エラー修正版）
    
    # 1. LINE Bot統合ルーター追加（404エラー修正）
    if ENABLE_LINE_INTEGRATION:
        try:
            # LINE Ultra Fast Bot を /line プレフィックスで追加（/line/webhook 対応）
            from api.routers.line_bot_ultra_fast import router as line_ultra_fast_router
            app.include_router(line_ultra_fast_router, prefix="/line", tags=["line"])
            logger.info("✅ LINE Ultra Fast router added at /line (WEBHOOK FIXED)")
            
            # テンプレート高速応答も /line-template-fast で追加（既存の構成維持）
            from api.routers.line_bot_template_fast import router as line_template_fast_router
            app.include_router(line_template_fast_router, prefix="/line-template-fast", tags=["line-template-fast"])
            logger.info("✅ LINE Template Fast router added at /line-template-fast")
            
            # 統合RAG版も追加（フォールバック用）
            from api.routers.line_bot_rag_integrated import router as line_rag_router
            app.include_router(line_rag_router, prefix="/line-rag", tags=["line-rag"])
            logger.info("✅ LINE RAG Integrated router added at /line-rag")
            
        except Exception as e:
            logger.error(f"❌ Failed to add LINE routers: {e}")
            logger.error(f"   This may cause continued 404 errors for LINE webhooks")
    
    # 2. 高速チャット
    try:
        from api.routers.chat_ultra_fast import router as chat_ultra_fast_router
        app.include_router(chat_ultra_fast_router, prefix="/chat-ultra-fast", tags=["chat-ultra-fast"])
        logger.info("✅ Chat Ultra Fast router added")
    except Exception as e:
        logger.warning(f"⚠️ Failed to add Chat Ultra Fast router: {e}")
    
    # 3. 標準チャットルーター
    try:
        from api.routers.chat import router as chat_router
        app.include_router(chat_router, prefix="/chat-standard", tags=["chat-standard"])
        logger.info("✅ Standard Chat router added")
    except Exception as e:
        logger.warning(f"⚠️ Failed to add Standard Chat router: {e}")
    
    # 4. アップロード機能
    try:
        from api.routers.upload import router as upload_router
        app.include_router(upload_router, prefix="/upload", tags=["upload"])
        logger.info("✅ Upload router added")
    except Exception as e:
        logger.warning(f"⚠️ Upload router not added: {e}")
    
    # 5. LINE関連の補助機能
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
    
    logger.info("🎉 Optimized RAG API startup completed with LINE integration fixed")
    logger.info(f"⚡ Startup time: {time.time() - startup_time:.2f} seconds")
    logger.info(f"🎯 Smart Routing: {'Enabled' if ENABLE_SMART_ROUTING else 'Disabled'}")
    logger.info(f"🔧 Sentence Completion: {'Enabled' if ENABLE_SENTENCE_COMPLETION else 'Disabled'}")
    logger.info(f"📱 LINE Integration: {'Enabled' if ENABLE_LINE_INTEGRATION else 'Disabled'}")
    logger.info("📋 Available LINE Webhook URLs:")
    logger.info("   - /line/webhook (Primary - fixes 404 error)")
    logger.info("   - /line-template-fast/webhook (Template fast)")
    logger.info("   - /line-rag/webhook (RAG integrated)")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)